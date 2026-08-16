from django.apps import AppConfig


class SesTrackingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ses_tracking'
    verbose_name = 'SES Event Tracking'

    # Picked up by the `setting` package's register_settings command, which
    # imports each entry as `<app>.settings.<name>.<name>`. The explicit 'app'
    # key is required: it is stored on SettingRecord and used to build that
    # import path, so it must match this app's dotted path exactly.
    CONFIGURATORS = [
        {
            'app': 'ses_tracking',
            'name': 'email_routing',
            'title': 'Email Routing by Role',
            'description': 'Which address(es) each role receives mail at',
            'categories': ['4'],
        },
    ]
