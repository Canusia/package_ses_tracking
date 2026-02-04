# ses_tracking/models.py
from django.db import models
from django.utils import timezone

from django.conf import settings


class SESEvent(models.Model):
    EVENT_TYPES = [
        ('bounce', 'Bounce'),
        ('complaint', 'Complaint'),
        ('delivery', 'Delivery'),
        ('send', 'Send'),
        ('reject', 'Reject'),
        ('rendering_failure', 'Rendering Failure'),
        ('delivery_delay', 'Delivery Delay'),
        ('subscription', 'Subscription'),
    ]
    
    BOUNCE_TYPES = [
        ('Permanent', 'Permanent'),
        ('Transient', 'Transient'),
        ('Undetermined', 'Undetermined'),
    ]
    

    event_type = models.CharField(max_length=20, choices=EVENT_TYPES, db_index=True)
    message_id = models.CharField(max_length=255, db_index=True)  # SES message ID
    email_message_id = models.CharField(max_length=500, null=True, blank=True, db_index=True)  # Email Message-ID header
    email = models.EmailField(db_index=True)
    email_subject = models.CharField(max_length=500, null=True, blank=True, db_index=True)  # Email Subject
    email_to = models.TextField(null=True, blank=True)  # To addresses (can be multiple, comma-separated)
    
    # Bounce specific
    bounce_type = models.CharField(max_length=20, choices=BOUNCE_TYPES, null=True, blank=True)
    bounce_sub_type = models.CharField(max_length=50, null=True, blank=True)
    
    # Complaint specific
    complaint_feedback_type = models.CharField(max_length=50, null=True, blank=True)
    
    # Reject specific
    reject_reason = models.CharField(max_length=255, null=True, blank=True)
    
    # Common fields
    timestamp = models.DateTimeField(db_index=True)
    raw_message = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'SES Event'
        verbose_name_plural = 'SES Events'
    
    def __str__(self):
        return f"{self.event_type.title()} - {self.email} - {self.timestamp}"
    
    @property
    def extract_email_subject(self):
        """Extract Subject from raw message headers"""
        try:
            # Try commonHeaders first (cleaner)
            subject = self.raw_message.get('mail', {}).get('commonHeaders', {}).get('subject')
            if subject:
                return subject
            
            # Fallback to headers array
            headers = self.raw_message.get('mail', {}).get('headers', [])
            for header in headers:
                if header.get('name') == 'Subject':
                    return header.get('value', '')
        except (AttributeError, KeyError):
            pass
        return None
    
    @property
    def extract_email_to(self):
        """Extract To addresses from raw message"""
        try:
            # Try commonHeaders first (cleaner, returns list)
            to_addresses = self.raw_message.get('mail', {}).get('commonHeaders', {}).get('to')
            if to_addresses:
                # Join list into comma-separated string
                return ', '.join(to_addresses)
            
            # Fallback to headers array
            headers = self.raw_message.get('mail', {}).get('headers', [])
            for header in headers:
                if header.get('name') == 'To':
                    return header.get('value', '')
        except (AttributeError, KeyError):
            pass
        return None
    
    @property
    def extract_email_message_id(self):
        """Extract Message-ID from raw message headers"""
        try:
            headers = self.raw_message.get('mail', {}).get('headers', [])
            for header in headers:
                if header.get('name') == 'Message-ID':
                    # Remove < and > brackets if present
                    msg_id = header.get('value', '')
                    return msg_id.strip('<>')
        except (AttributeError, KeyError):
            pass
        return None
    
    def save(self, *args, **kwargs):
        """Extract and save email metadata before saving"""
        if not self.email_message_id and self.raw_message:
            self.email_message_id = self.extract_email_message_id
        if not self.email_subject and self.raw_message:
            self.email_subject = self.extract_email_subject
        if not self.email_to and self.raw_message:
            self.email_to = self.extract_email_to
        super().save(*args, **kwargs)


class DailyEmailStats(models.Model):
    """
    Aggregated daily statistics for email events
    """
    date = models.DateField(unique=True, db_index=True)
    
    # Event counts
    total_sends = models.IntegerField(default=0)
    total_deliveries = models.IntegerField(default=0)
    total_bounces = models.IntegerField(default=0)
    total_complaints = models.IntegerField(default=0)
    total_rejects = models.IntegerField(default=0)
    total_rendering_failures = models.IntegerField(default=0)
    total_delivery_delays = models.IntegerField(default=0)
    total_subscriptions = models.IntegerField(default=0)
    
    # Bounce breakdown
    permanent_bounces = models.IntegerField(default=0)
    transient_bounces = models.IntegerField(default=0)
    undetermined_bounces = models.IntegerField(default=0)
    
    # Calculated rates (stored as percentages)
    bounce_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)  # e.g., 2.50 for 2.5%
    complaint_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    delivery_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Unique recipients
    unique_recipients = models.IntegerField(default=0)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-date']
        verbose_name = 'Daily Email Statistics'
        verbose_name_plural = 'Daily Email Statistics'
        indexes = [
            models.Index(fields=['-date']),
        ]
    
    def __str__(self):
        return f"Stats for {self.date}"
    
    def calculate_rates(self):
        """Calculate bounce, complaint, and delivery rates"""
        # Use deliveries as the base if sends is 0 (SES might not track sends)
        base_count = self.total_sends if self.total_sends > 0 else self.total_deliveries
        
        if base_count > 0:
            self.bounce_rate = (self.total_bounces / base_count) * 100
            self.complaint_rate = (self.total_complaints / base_count) * 100
            self.delivery_rate = (self.total_deliveries / base_count) * 100
        else:
            self.bounce_rate = 0
            self.complaint_rate = 0
            self.delivery_rate = 0

    @classmethod
    def is_bounce_rate_acceptable(cls, threshold=5.0, date=None):
        """
        Check if bounce rate is below threshold for given date.
        
        Args:
            threshold: Maximum acceptable bounce rate percentage (default 5.0)
            date: Date to check (default: today)
            
        Returns:
            tuple: (is_acceptable: bool, current_rate: Decimal, stats: DailyEmailStats or None)
        """
        # Check override setting first
        if getattr(settings, 'OVERRIDE_BOUNCE_RATE', False):
            return (True, 0, None)
        
        if date is None:
            date = timezone.now().date()
        
        try:
            stats = cls.objects.get(date=date)
            is_acceptable = stats.bounce_rate <= threshold
            return (is_acceptable, stats.bounce_rate, stats)
        except cls.DoesNotExist:
            return (True, 0, None)  # No data yet, assume acceptable