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
    message_id = models.CharField(max_length=255, db_index=True)
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
