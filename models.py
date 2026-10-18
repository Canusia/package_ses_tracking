# ses_tracking/models.py
import uuid

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
        ('open', 'Open'),
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

    # Campus the mail was sent for (#3), from the event's configuration set
    # via SES_CAMPUS_CONFIG. Blank on single-campus deployments.
    campus_code = models.CharField(max_length=50, blank=True, default='', db_index=True)

    # The sent message this event is about, from the `myce-id` message tag
    # (sent-email log). Null for older mail and other senders on the set.
    sent_email = models.ForeignKey(
        'SentEmail', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='events')

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'SES Event'
        verbose_name_plural = 'SES Events'
    
    def __str__(self):
        return f"{self.event_type.title()} - {self.email} - {self.timestamp}"

    @staticmethod
    def campus_from_raw_message(raw_message):
        """SES puts the configuration set in mail.tags['ses:configuration-set']."""
        from .campus_mail import campus_for_configuration_set
        try:
            tag = ((raw_message or {}).get('mail') or {}).get('tags', {}).get(
                'ses:configuration-set')
        except AttributeError:
            return ''
        if isinstance(tag, list):
            tag = tag[0] if tag else None
        return campus_for_configuration_set(tag)
    
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
        if not self.campus_code and self.raw_message:
            self.campus_code = self.campus_from_raw_message(self.raw_message)
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

class SentEmail(models.Model):
    """One outgoing message as it left MyCE, after routing.

    Written by ses_tracking.capture from RoutingBackend.send_messages(); its
    id travels to SES as the `myce-id` message tag so SNS events can find it.
    """
    PATH_QUEUE = 'queue'
    PATH_DIRECT = 'direct'
    PATH_CHOICES = [(PATH_QUEUE, 'Queued (django-mailer)'), (PATH_DIRECT, 'Direct')]

    SMTP_SENT = 'sent'
    SMTP_FAILED = 'failed'
    SMTP_CHOICES = [(SMTP_SENT, 'Sent'), (SMTP_FAILED, 'Failed')]

    STATUS_CHOICES = [
        ('sent', 'Sent'), ('delayed', 'Delayed'), ('delivered', 'Delivered'),
        ('rejected', 'Rejected'), ('bounced', 'Bounced'), ('complained', 'Complained'),
    ]
    # Forward-only: an event never moves status to a lower rank, so a late
    # delivery cannot overwrite a bounce.
    STATUS_RANK = {'sent': 0, 'delayed': 1, 'delivered': 2,
                   'rejected': 3, 'bounced': 3, 'complained': 4}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    original_to = models.JSONField(default=list)
    original_cc = models.JSONField(default=list)
    original_bcc = models.JSONField(default=list)
    delivered_to = models.JSONField(default=list)
    delivered_cc = models.JSONField(default=list)
    delivered_bcc = models.JSONField(default=list)
    # Lower-cased, space-joined union of every original and delivered
    # address, for staff free-text search. Not btree-indexed: a big send
    # would exceed the index row size, and contains-search can't use it.
    # Exact per-person lookups go through SentEmailRecipient instead.
    search_addresses = models.TextField(blank=True, default='')
    from_email = models.CharField(max_length=320, blank=True, default='')
    subject = models.CharField(max_length=998, blank=True, default='', db_index=True)
    text_body = models.TextField(null=True, blank=True)
    html_body = models.TextField(null=True, blank=True)
    body_pruned_at = models.DateTimeField(null=True, blank=True)
    path = models.CharField(max_length=10, choices=PATH_CHOICES)
    campus_code = models.CharField(max_length=50, blank=True, default='', db_index=True)
    debug_routed = models.BooleanField(default=False)
    sent_at = models.DateTimeField(default=timezone.now, db_index=True)
    smtp_status = models.CharField(max_length=10, choices=SMTP_CHOICES, blank=True, default='')
    smtp_error = models.TextField(blank=True, default='')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='sent', db_index=True)
    first_opened_at = models.DateTimeField(null=True, blank=True, db_index=True)
    open_count = models.PositiveIntegerField(default=0)
    # SES can only track opens in mail with an HTML part.
    trackable = models.BooleanField(default=False)

    class Meta:
        ordering = ['-sent_at']
        verbose_name = 'Sent email'
        permissions = [('view_sent_email', 'Can view sent email')]

    def __str__(self):
        return f'{self.subject} -> {", ".join(self.delivered_to)}'

    def advance(self, status):
        """Move status forward to `status`; return False if that would go back."""
        if self.STATUS_RANK.get(status, -1) <= self.STATUS_RANK.get(self.status, 0):
            return False
        self.status = status
        self.save(update_fields=['status'])
        return True

    def record_open(self, when):
        self.open_count += 1
        fields = ['open_count']
        if self.first_opened_at is None:
            self.first_opened_at = when
            fields.append('first_opened_at')
        self.save(update_fields=fields)


class SentEmailRecipient(models.Model):
    """One lower-cased address (original or delivered) of a SentEmail, so the
    person Emails tab is an indexed exact lookup, not a table scan."""
    sent_email = models.ForeignKey(SentEmail, on_delete=models.CASCADE, related_name='recipients')
    address = models.CharField(max_length=320, db_index=True)

    class Meta:
        unique_together = [('sent_email', 'address')]
