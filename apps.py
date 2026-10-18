from django.apps import AppConfig


class SesTrackingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ses_tracking'
    verbose_name = 'SES Event Tracking'

    # Picked up by the `setting` package's register_settings command, which
    # imports each entry as `<app>.settings.<name>.<name>`. The explicit 'app'
    # key is required: it is stored on SettingRecord and used to build that
    # import path, so it must match this app's dotted path exactly.
    def ready(self):
        # Emails tab on the person detail pages that have a tab registry.
        from . import tabs
        tabs.register()

        # Stamp queued mail with its campus at enqueue time (#3). django-mailer
        # is optional for this package.
        try:
            from django.db.models.signals import pre_save
            from mailer.models import Message
        except Exception:
            return
        from .campus_mail import stamp_queued_message
        pre_save.connect(
            stamp_queued_message, sender=Message,
            dispatch_uid='ses_tracking_stamp_queued_message')

    CONFIGURATORS = [
        {
            'app': 'ses_tracking',
            'name': 'email_routing',
            'title': 'Email Routing by Role',
            'description': 'Which address(es) each role receives mail at',
            'categories': ['4'],
        },
        {
            'app': 'ses_tracking',
            'name': 'sent_email',
            'title': 'Sent Email',
            'description': 'How long sent mail and message bodies are kept',
            'categories': ['4'],
        },
    ]
