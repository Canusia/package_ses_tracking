"""Retention for SentEmail: clear old message bodies, delete old records."""
import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from ses_tracking.models import SentEmail, SESEvent
from ses_tracking.settings.sent_email import retention

BATCH = 1000


class Command(BaseCommand):
    help = 'Clear sent-email bodies and delete sent-email records past their retention.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        # cron_jobs calls every scheduled command with time=<scheduled time>.
        parser.add_argument('--time', default=None)

    def handle(self, *args, dry_run=False, **options):
        body_days, log_days = retention()
        now = timezone.now()
        bodies = SentEmail.objects.filter(
            sent_at__lt=now - datetime.timedelta(days=body_days), body_pruned_at__isnull=True)
        old = SentEmail.objects.filter(sent_at__lt=now - datetime.timedelta(days=log_days))

        if dry_run:
            self.stdout.write(
                f'would clear {bodies.count()} bodies, would delete {old.count()} records')
            return

        cleared = deleted = 0
        while ids := list(bodies.values_list('pk', flat=True)[:BATCH]):
            cleared += SentEmail.objects.filter(pk__in=ids).update(
                text_body=None, html_body=None, body_pruned_at=now)
        while ids := list(old.values_list('pk', flat=True)[:BATCH]):
            SESEvent.objects.filter(sent_email_id__in=ids).delete()
            deleted += SentEmail.objects.filter(pk__in=ids).delete()[0]
        self.stdout.write(f'cleared {cleared} bodies, deleted {deleted} records')
