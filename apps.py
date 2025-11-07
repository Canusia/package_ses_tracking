from django.apps import AppConfig


class SesTrackingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ses_tracking'
    verbose_name = 'SES Event Tracking'