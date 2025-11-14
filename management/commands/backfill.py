# ses_tracking/management/commands/aggregate_daily_stats.py
from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from django.utils import timezone
from ses_tracking.models import SESEvent, DailyEmailStats
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Aggregate SES events into daily statistics'

    def add_arguments(self, parser):
        ...

    def handle(self, *args, **options):
        # Django shell
        from ses_tracking.models import SESEvent

        for event in SESEvent.objects.filter(email_message_id__isnull=True):
            event.save()  # This will trigger the save() method to extract Message-ID

        self.stdout.write(self.style.SUCCESS('Successfully backfilled ID'))
