from django.db import migrations


def seed_crontab(apps, schema_editor):
    """Schedule the daily retention prune through cis's CronTab (cron_jobs)."""
    try:
        CronTab = apps.get_model('cis', 'CronTab')
    except LookupError:
        return
    CronTab.objects.get_or_create(command='prune_sent_email', defaults={'cron': '15 3 * * *'})


class Migration(migrations.Migration):

    dependencies = [
        ('ses_tracking', '0006_sentemail'),
        ('cis', '__first__'),
    ]

    operations = [
        migrations.RunPython(seed_crontab, migrations.RunPython.noop),
    ]
