"""SES events are linked to their SentEmail through mail.tags['myce-id']
(sent-email spec §2)."""
from django.test import TestCase
from django.utils import timezone

from ses_tracking import views
from ses_tracking.models import SentEmail, SESEvent


def _ses(event_type, sent_email=None, extra=None, message_id='m-1'):
    tags = {'ses:configuration-set': ['ewu-config-set']}
    if sent_email:
        tags['myce-id'] = [sent_email.id.hex]
    msg = {
        'eventType': event_type,
        'mail': {'messageId': message_id, 'timestamp': timezone.now().isoformat(),
                 'tags': tags, 'headers': [], 'commonHeaders': {'to': ['a@x.com']}},
    }
    msg.update(extra or {})
    return msg


class EventLinkTests(TestCase):

    def setUp(self):
        self.row = SentEmail.objects.create(path='queue', delivered_to=['a@x.com'])

    def test_delivery_links_and_advances(self):
        views.handle_delivery(_ses('Delivery', self.row, {'delivery': {
            'timestamp': timezone.now().isoformat(), 'recipients': ['a@x.com']}}))
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'delivered')
        self.assertEqual(SESEvent.objects.get().sent_email, self.row)

    def test_bounce_after_delivery_wins_and_delivery_after_bounce_does_not(self):
        views.handle_bounce(_ses('Bounce', self.row, {'bounce': {
            'bounceType': 'Permanent', 'bouncedRecipients': [{'emailAddress': 'a@x.com'}]}}))
        views.handle_delivery(_ses('Delivery', self.row, {'delivery': {
            'recipients': ['a@x.com']}}))
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'bounced')

    def test_open_counts_without_changing_status(self):
        views.handle_open(_ses('Open', self.row, {'open': {
            'timestamp': timezone.now().isoformat(), 'userAgent': 'x', 'ipAddress': '1.1.1.1'}}))
        self.row.refresh_from_db()
        self.assertEqual(self.row.open_count, 1)
        self.assertIsNotNone(self.row.first_opened_at)
        self.assertEqual(self.row.status, 'sent')
        self.assertEqual(SESEvent.objects.get().event_type, 'open')

    def test_duplicate_open_notification_counts_once(self):
        payload = _ses('Open', self.row, {'open': {'timestamp': timezone.now().isoformat()}})
        views.handle_open(payload)
        views.handle_open(payload)
        self.row.refresh_from_db()
        self.assertEqual(self.row.open_count, 1)

    def test_untagged_event_is_stored_unlinked(self):
        views.handle_delivery(_ses('Delivery', None, {'delivery': {'recipients': ['a@x.com']}}))
        self.assertIsNone(SESEvent.objects.get().sent_email)

    def test_unknown_or_malformed_tag_is_stored_unlinked(self):
        msg = _ses('Delivery', None, {'delivery': {'recipients': ['a@x.com']}})
        msg['mail']['tags']['myce-id'] = ['not-a-uuid']
        views.handle_delivery(msg)
        self.assertIsNone(SESEvent.objects.get().sent_email)

    def test_sns_endpoint_dispatches_open(self):
        from unittest.mock import patch
        import json
        body = {'Type': 'Notification', 'Message': json.dumps(_ses('Open', self.row, {
            'open': {'timestamp': timezone.now().isoformat()}}))}
        with patch('ses_tracking.views.verify_sns_message'):
            resp = self.client.post('/ses/webhooks/sns/ses-events/', json.dumps(body),
                                    content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.row.refresh_from_db()
        self.assertEqual(self.row.open_count, 1)


class OpenDedupeWithoutTimestampTests(TestCase):

    def test_repeat_of_an_open_with_no_timestamps_counts_once(self):
        row = SentEmail.objects.create(path='queue', delivered_to=['a@x.com'])
        payload = _ses('Open', row, {'open': {'userAgent': 'x'}})
        del payload['mail']['timestamp']
        views.handle_open(payload)
        views.handle_open(payload)
        row.refresh_from_db()
        self.assertEqual(row.open_count, 1)


class DailyStatsRecipientsTests(TestCase):

    def test_opens_do_not_count_as_extra_recipients(self):
        from io import StringIO
        from django.core.management import call_command
        from ses_tracking.models import DailyEmailStats
        now = timezone.now()
        SESEvent.objects.create(event_type='send', message_id='m', email='a@x.com',
                                timestamp=now, raw_message={})
        SESEvent.objects.create(event_type='open', message_id='m2', email='old@x.com',
                                timestamp=now, raw_message={})
        call_command('aggregate_daily_stats', '--date', timezone.localdate(now).isoformat(),
                     stdout=StringIO())
        self.assertEqual(DailyEmailStats.objects.get().unique_recipients, 1)
