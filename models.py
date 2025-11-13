# ses_tracking/models.py
from django.db import models
from django.utils import timezone


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
        """Extract and save email_message_id before saving"""
        if not self.email_message_id and self.raw_message:
            self.email_message_id = self.extract_email_message_id
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
        if self.total_sends > 0:
            self.bounce_rate = (self.total_bounces / self.total_sends) * 100
            self.complaint_rate = (self.total_complaints / self.total_sends) * 100
            self.delivery_rate = (self.total_deliveries / self.total_sends) * 100
        else:
            self.bounce_rate = 0
            self.complaint_rate = 0
            self.delivery_rate = 0
