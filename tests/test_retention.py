"""Retention: bodies cleared after body_retention_days, records deleted after
log_retention_days (sent-email spec §6)."""
import datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from ses_tracking.models import SentEmail, SESEvent


class PruneTests(TestCase):

    def _row(self, days_old):
        row = SentEmail.objects.create(path='queue', text_body='t', html_body='<p>h</p>')
        SentEmail.objects.filter(pk=row.pk).update(
            sent_at=timezone.now() - datetime.timedelta(days=days_old))
        return row

    def test_bodies_cleared_after_180_days_rows_kept(self):
        old, new = self._row(181), self._row(10)
        call_command('prune_sent_email', stdout=StringIO())
        old.refresh_from_db()
        new.refresh_from_db()
        self.assertIsNone(old.text_body)
        self.assertIsNone(old.html_body)
        self.assertIsNotNone(old.body_pruned_at)
        self.assertEqual(new.text_body, 't')

    def test_rows_and_events_deleted_after_730_days(self):
        old = self._row(731)
        SESEvent.objects.create(event_type='delivery', message_id='m', email='a@x.com',
                                timestamp=timezone.now(), raw_message={}, sent_email=old)
        call_command('prune_sent_email', stdout=StringIO())
        self.assertFalse(SentEmail.objects.filter(pk=old.pk).exists())
        self.assertFalse(SESEvent.objects.filter(message_id='m').exists())

    def test_dry_run_changes_nothing(self):
        old = self._row(800)
        out = StringIO()
        call_command('prune_sent_email', '--dry-run', stdout=out)
        self.assertTrue(SentEmail.objects.filter(pk=old.pk).exists())
        self.assertIn('would delete 1', out.getvalue())

    def test_accepts_the_time_kwarg_cron_jobs_passes(self):
        call_command('prune_sent_email', time='2026-10-18 03:15:00', stdout=StringIO())

    def test_custom_retention_from_setting(self):
        from cis.models.settings import Setting
        Setting.objects.create(key='ses_tracking.settings.sent_email',
                               value={'body_retention_days': 30, 'log_retention_days': 60})
        row = self._row(45)
        call_command('prune_sent_email', stdout=StringIO())
        row.refresh_from_db()
        self.assertIsNone(row.text_body)

    def test_scheduled_job_is_seeded(self):
        from cis.models.crontab import CronTab
        self.assertTrue(CronTab.objects.filter(command='prune_sent_email').exists())


class RetentionFormTests(TestCase):

    def test_bodies_cannot_outlive_records(self):
        from django.test import RequestFactory
        from ses_tracking.settings.sent_email import sent_email
        form = sent_email(RequestFactory().get('/?report_id=1'),
                          data={'body_retention_days': 900, 'log_retention_days': 730})
        self.assertFalse(form.is_valid())
