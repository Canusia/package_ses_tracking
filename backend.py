from django.conf import settings
import logging

logger = logging.getLogger(__name__)

from django.core.mail.backends.smtp import EmailBackend as SMTPBackend

class SESBackend(SMTPBackend):
    """
    Custom email backend that wraps SMTP backend and adds SES configuration set header
    for tracking bounces/complaints.
    """
    
    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        
        # Get SES settings from Django settings
        self.aws_region = getattr(settings, 'AWS_SES_REGION', 'us-east-1')
        self.configuration_set = getattr(settings, 'AWS_SES_CONFIGURATION_SET', 'rmu-config-set')
    
    def _send(self, email_message):
        # Add configuration set header
        if not hasattr(email_message, 'extra_headers'):
            email_message.extra_headers = {}
        
        email_message.extra_headers['X-SES-CONFIGURATION-SET'] = self.configuration_set
        
        # Call the original _send method of the parent SMTP backend
        return super()._send(email_message)