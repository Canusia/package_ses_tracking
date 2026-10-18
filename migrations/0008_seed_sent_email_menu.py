from django.db import migrations


def seed_menu(apps, schema_editor):
    from ses_tracking.migrations._menu import add_sent_email
    try:
        Setting = apps.get_model('cis', 'Setting')
    except LookupError:
        return
    add_sent_email(Setting)


class Migration(migrations.Migration):

    dependencies = [
        ('ses_tracking', '0007_seed_prune_crontab'),
        ('cis', '__first__'),
    ]

    operations = [
        migrations.RunPython(seed_menu, migrations.RunPython.noop),
    ]
