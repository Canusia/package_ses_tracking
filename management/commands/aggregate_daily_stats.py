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
        parser.add_argument(
            '--date',
            type=str,
            help='Specific date to process (YYYY-MM-DD). Defaults to yesterday.'
        )
        parser.add_argument(
            '--days',
            type=int,
            default=1,
            help='Number of days to process backwards from date/yesterday'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force regeneration of stats even if they already exist'
        )

    def handle(self, *args, **options):
        # Determine date range
        if options['date']:
            end_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
        else:
            end_date = (timezone.now() - timedelta(days=1)).date()
        
        days_back = options['days']
        start_date = end_date - timedelta(days=days_back - 1)
        
        self.stdout.write(f"Processing stats from {start_date} to {end_date}")
        
        # Process each day
        current_date = start_date
        while current_date <= end_date:
            self.process_day(current_date, force=options['force'])
            current_date += timedelta(days=1)
        
        self.stdout.write(self.style.SUCCESS('Successfully aggregated daily stats'))

    def process_day(self, date, force=False):
        """Process statistics for a single day"""
        
        # Check if stats already exist
        if not force and DailyEmailStats.objects.filter(date=date).exists():
            self.stdout.write(f"Stats for {date} already exist (use --force to regenerate)")
            return
        
        # Get events for this day
        events = SESEvent.objects.filter(
            timestamp__date=date
        )
        
        # Aggregate counts by event type
        stats = events.aggregate(
            total_sends=Count('id', filter=Q(event_type='send')),
            total_deliveries=Count('id', filter=Q(event_type='delivery')),
            total_bounces=Count('id', filter=Q(event_type='bounce')),
            total_complaints=Count('id', filter=Q(event_type='complaint')),
            total_rejects=Count('id', filter=Q(event_type='reject')),
            total_rendering_failures=Count('id', filter=Q(event_type='rendering_failure')),
            total_delivery_delays=Count('id', filter=Q(event_type='delivery_delay')),
            total_subscriptions=Count('id', filter=Q(event_type='subscription')),
        )
        
        # Bounce type breakdown
        bounce_stats = events.filter(event_type='bounce').aggregate(
            permanent_bounces=Count('id', filter=Q(bounce_type='Permanent')),
            transient_bounces=Count('id', filter=Q(bounce_type='Transient')),
            undetermined_bounces=Count('id', filter=Q(bounce_type='Undetermined')),
        )
        
        # Unique recipients
        unique_recipients = events.values('email').distinct().count()
        
        # Combine all stats
        all_stats = {
            **stats,
            **bounce_stats,
            'unique_recipients': unique_recipients,
        }
        
        # Create or update daily stats
        daily_stat, created = DailyEmailStats.objects.update_or_create(
            date=date,
            defaults=all_stats
        )
        
        # Calculate rates
        daily_stat.calculate_rates()
        daily_stat.save()
        
        action = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} stats for {date}: "
                f"{daily_stat.total_sends} sends, "
                f"{daily_stat.total_deliveries} deliveries, "
                f"{daily_stat.total_bounces} bounces"
            )
        )
        
        logger.info(f"Aggregated daily stats for {date}")