"""SentEmail: every outgoing message recorded after routing and tagged
`myce-id` for SES (sent-email spec §1)."""
import datetime

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone

from ses_tracking.models import SentEmail


class SentEmailModelTests(TestCase):

    def _row(self, **kw):
        return SentEmail.objects.create(
            from_email='f@x.com', subject='S', path=SentEmail.PATH_QUEUE, **kw)

    def test_status_only_moves_forward(self):
        row = self._row()
        self.assertTrue(row.advance('delivered'))
        self.assertTrue(row.advance('bounced'))
        self.assertFalse(row.advance('delivered'))
        row.refresh_from_db()
        self.assertEqual(row.status, 'bounced')

    def test_open_sets_first_open_once_and_counts(self):
        row = self._row()
        first = timezone.now()
        row.record_open(first)
        row.record_open(first + datetime.timedelta(hours=1))
        row.refresh_from_db()
        self.assertEqual(row.open_count, 2)
        self.assertEqual(row.first_opened_at, first)

    def test_permission_exists(self):
        self.assertTrue(Permission.objects.filter(
            content_type__app_label='ses_tracking', codename='view_sent_email').exists())


# --- Capture (Task 2) -------------------------------------------------------

from unittest.mock import patch

from django.core import mail
from django.core.mail import EmailMessage, EmailMultiAlternatives, get_connection
from django.test import override_settings

LOCMEM = 'django.core.mail.backends.locmem.EmailBackend'
ROUTING = 'ses_tracking.backend.RoutingBackend'
TAG_HEADER = 'X-SES-MESSAGE-TAGS'


@override_settings(EMAIL_BACKEND=ROUTING, SES_TRACKING_ROUTING_INNER_BACKEND=LOCMEM)
class CaptureTests(TestCase):

    def setUp(self):
        mail.outbox = []
        p = patch('ses_tracking.backend.load_config', return_value={})
        p.start()
        self.addCleanup(p.stop)

    def test_direct_send_writes_a_row_and_tags_the_message(self):
        EmailMessage('Hello', 'Body', 'from@x.com', ['a@x.com']).send()
        row = SentEmail.objects.get()
        self.assertEqual(row.delivered_to, ['a@x.com'])
        self.assertEqual(row.original_to, ['a@x.com'])
        self.assertEqual(row.path, SentEmail.PATH_DIRECT)
        self.assertEqual(row.smtp_status, SentEmail.SMTP_SENT)
        self.assertFalse(row.trackable)
        self.assertIn(f'myce-id={row.id.hex}', mail.outbox[0].extra_headers[TAG_HEADER])

    def test_html_message_is_trackable_and_keeps_both_bodies(self):
        m = EmailMultiAlternatives('S', 'text part', 'f@x.com', ['a@x.com'])
        m.attach_alternative('<p>html part</p>', 'text/html')
        m.send()
        row = SentEmail.objects.get()
        self.assertTrue(row.trackable)
        self.assertEqual(row.text_body, 'text part')
        self.assertEqual(row.html_body, '<p>html part</p>')

    def test_each_message_in_a_batch_gets_its_own_row(self):
        get_connection().send_messages([
            EmailMessage('One', 'b', 'f@x.com', ['a@x.com']),
            EmailMessage('Two', 'b', 'f@x.com', ['b@x.com']),
        ])
        self.assertEqual(SentEmail.objects.count(), 2)
        tags = {m.extra_headers[TAG_HEADER] for m in mail.outbox}
        self.assertEqual(len(tags), 2)

    def test_existing_tag_header_is_kept(self):
        EmailMessage('S', 'b', 'f@x.com', ['a@x.com'],
                     headers={TAG_HEADER: 'campaign=fall'}).send()
        header = mail.outbox[0].extra_headers[TAG_HEADER]
        self.assertIn('campaign=fall', header)
        self.assertIn('myce-id=', header)

    def test_search_addresses_cover_original_and_delivered_lower_cased(self):
        EmailMessage('S', 'b', 'f@x.com', ['A@X.com'], cc=['c@x.com']).send()
        row = SentEmail.objects.get()
        self.assertIn('a@x.com', row.search_addresses.split())
        self.assertIn('c@x.com', row.search_addresses.split())

    def test_routed_message_keeps_original_and_delivered_apart(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group
        user = get_user_model().objects.create(
            username='t@college.edu', email='t@college.edu', secondary_email='t@home.com')
        user.groups.add(Group.objects.get_or_create(name='instructor')[0])
        with patch('ses_tracking.backend.load_config',
                   return_value={'mode': 'active', 'roles': {'instructor': ['secondary']}}):
            EmailMessage('S', 'b', 'f@x.com', ['t@college.edu']).send()
        row = SentEmail.objects.get()
        self.assertEqual(row.original_to, ['t@college.edu'])
        self.assertEqual(row.delivered_to, ['t@home.com'])

    def test_failed_send_is_recorded_and_still_raises(self):
        with patch('django.core.mail.backends.locmem.EmailBackend.send_messages',
                   side_effect=OSError('smtp down')):
            with self.assertRaises(OSError):
                EmailMessage('S', 'b', 'f@x.com', ['a@x.com']).send()
        row = SentEmail.objects.get()
        self.assertEqual(row.smtp_status, SentEmail.SMTP_FAILED)
        self.assertIn('smtp down', row.smtp_error)

    def test_capture_error_never_stops_the_mail(self):
        with patch('ses_tracking.capture.SentEmail.objects.create', side_effect=RuntimeError):
            EmailMessage('S', 'b', 'f@x.com', ['a@x.com']).send()
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn(TAG_HEADER, mail.outbox[0].extra_headers)


class QueuedPathTests(TestCase):

    def test_routing_ses_backend_records_queue_path(self):
        from ses_tracking.backend import RoutingSESBackend
        with patch('ses_tracking.backend.load_config', return_value={}), \
                patch('ses_tracking.backend.SESBackend.send_messages', return_value=1):
            RoutingSESBackend().send_messages(
                [EmailMessage('S', 'b', 'f@x.com', ['a@x.com'])])
        self.assertEqual(SentEmail.objects.get().path, SentEmail.PATH_QUEUE)
