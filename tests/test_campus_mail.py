"""Per-campus default sender and SES configuration set (#3)."""
import uuid
from unittest import mock

from django.core import mail
from django.core.mail import EmailMessage
from django.test import TestCase, override_settings

from ses_tracking import campus_mail
from ses_tracking.backend import RoutingBackend, SESBackend
from ses_tracking.models import SESEvent

DEFAULT_FROM = 'noreply@myce.edu'
CONFIG = {
    'LAMAR_A': {'from_email': 'noreply@lit.edu', 'configuration_set': 'lamar-lit'},
    'LAMAR_B': {'from_email': 'noreply@lamarpa.edu', 'configuration_set': 'lamar-lscpa'},
}
LOCMEM = 'django.core.mail.backends.locmem.EmailBackend'


def _campus(code):
    return mock.MagicMock(code=code)


def in_campus(code):
    """Patch the campus that cis.campus_context reports."""
    return mock.patch('cis.campus_context.current_campus_or_none',
                      return_value=_campus(code) if code else None)


def _message(from_email=DEFAULT_FROM):
    return EmailMessage('s', 'b', from_email, ['to@x.com'])


class _SESSendTest(TestCase):
    """Drives SESBackend._send with SMTP's own _send replaced by a recorder."""

    def setUp(self):
        self.sent = []
        patcher = mock.patch(
            'django.core.mail.backends.smtp.EmailBackend._send',
            side_effect=lambda msg: self.sent.append(msg) or True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def deliver(self, message):
        SESBackend()._send(message)
        return self.sent[-1]

    def payload_headers(self, message):
        return dict(message.message().items())


@override_settings(DEFAULT_FROM_EMAIL=DEFAULT_FROM, AWS_SES_CONFIGURATION_SET='tenant-set')
class SingleCampusTest(_SESSendTest):
    def test_unchanged_without_campus_config(self):
        with in_campus('EWU') as lookup:
            sent = self.deliver(_message())
        self.assertEqual(sent.from_email, DEFAULT_FROM)
        self.assertEqual(sent.extra_headers['X-SES-CONFIGURATION-SET'], 'tenant-set')
        lookup.assert_not_called()  # zero cost when unconfigured

    @override_settings(AWS_SES_CONFIGURATION_SET=None)
    def test_unset_configuration_set_sends_no_header(self):
        sent = self.deliver(_message())
        self.assertNotIn('X-SES-CONFIGURATION-SET', sent.extra_headers)
        self.assertNotIn('X-SES-CONFIGURATION-SET', self.payload_headers(sent))

    def test_no_rmu_fallback_when_setting_absent(self):
        from django.conf import settings
        with self.settings():
            del settings.AWS_SES_CONFIGURATION_SET
            sent = self.deliver(_message())
        self.assertNotIn('X-SES-CONFIGURATION-SET', sent.extra_headers)


@override_settings(DEFAULT_FROM_EMAIL=DEFAULT_FROM, AWS_SES_CONFIGURATION_SET='tenant-set',
                   SES_CAMPUS_CONFIG=CONFIG)
class MultiCampusSESTest(_SESSendTest):
    def test_direct_send_under_campus(self):
        with in_campus('LAMAR_A'):
            sent = self.deliver(_message())
        self.assertEqual(sent.from_email, 'noreply@lit.edu')
        self.assertEqual(sent.extra_headers['X-SES-CONFIGURATION-SET'], 'lamar-lit')

    def test_stamp_wins_over_flush_context(self):
        message = _message()
        with in_campus('LAMAR_B'):
            campus_mail.stamp(message)
        with in_campus(None):  # flush runs with no campus
            sent = self.deliver(message)
        self.assertEqual(sent.from_email, 'noreply@lamarpa.edu')
        self.assertEqual(sent.extra_headers['X-SES-CONFIGURATION-SET'], 'lamar-lscpa')

    def test_explicit_sender_kept_but_set_follows_campus(self):
        with in_campus('LAMAR_A'):
            sent = self.deliver(_message('support@lit.edu'))
        self.assertEqual(sent.from_email, 'support@lit.edu')
        self.assertEqual(sent.extra_headers['X-SES-CONFIGURATION-SET'], 'lamar-lit')

    def test_display_name_kept_when_default_swapped(self):
        with in_campus('LAMAR_A'):
            sent = self.deliver(_message(f'CE Office <{DEFAULT_FROM}>'))
        self.assertEqual(sent.from_email, 'CE Office <noreply@lit.edu>')

    def test_no_campus_context_uses_deployment_defaults(self):
        with in_campus(None):
            sent = self.deliver(_message())
        self.assertEqual(sent.from_email, DEFAULT_FROM)
        self.assertEqual(sent.extra_headers['X-SES-CONFIGURATION-SET'], 'tenant-set')

    def test_unlisted_campus_falls_back(self):
        with in_campus('OTHER'):
            sent = self.deliver(_message())
        self.assertEqual(sent.from_email, DEFAULT_FROM)
        self.assertEqual(sent.extra_headers['X-SES-CONFIGURATION-SET'], 'tenant-set')

    def test_internal_header_never_reaches_payload(self):
        message = _message()
        with in_campus('LAMAR_A'):
            campus_mail.stamp(message)
            sent = self.deliver(message)
        self.assertNotIn('X-MyCE-Campus', sent.extra_headers)
        self.assertNotIn('X-MyCE-Campus', self.payload_headers(sent))

    def test_no_cis_means_no_stamp(self):
        message = _message()
        with mock.patch.dict('sys.modules', {'cis.campus_context': None}):
            campus_mail.stamp(message)
        self.assertNotIn('X-MyCE-Campus', message.extra_headers)


@override_settings(DEFAULT_FROM_EMAIL=DEFAULT_FROM, SES_CAMPUS_CONFIG=CONFIG,
                   EMAIL_BACKEND='ses_tracking.backend.RoutingBackend',
                   SES_TRACKING_ROUTING_INNER_BACKEND=LOCMEM)
class RoutingBackendCampusTest(TestCase):
    def setUp(self):
        mail.outbox = []

    @mock.patch('ses_tracking.backend.load_config', return_value={})
    def test_non_ses_inner_gets_sender_and_no_internal_header(self, _cfg):
        with in_campus('LAMAR_B'):
            RoutingBackend().send_messages([_message()])
        sent = mail.outbox[0]
        self.assertEqual(sent.from_email, 'noreply@lamarpa.edu')
        self.assertNotIn('X-MyCE-Campus', sent.extra_headers)


@override_settings(DEFAULT_FROM_EMAIL=DEFAULT_FROM, AWS_SES_CONFIGURATION_SET='tenant-set',
                   SES_CAMPUS_CONFIG=CONFIG)
class QueuedMailTest(_SESSendTest):
    def test_enqueued_under_b_flushed_without_campus(self):
        from mailer import send_html_mail
        from mailer.models import Message
        with in_campus('LAMAR_B'):
            send_html_mail('s', 'b', '<p>b</p>', DEFAULT_FROM, ['to@x.com'])
        row = Message.objects.latest('pk')
        self.assertEqual(row.email.extra_headers['X-MyCE-Campus'], 'LAMAR_B')

        with in_campus(None):
            sent = self.deliver(row.email)
        self.assertEqual(sent.from_email, 'noreply@lamarpa.edu')
        self.assertEqual(sent.extra_headers['X-SES-CONFIGURATION-SET'], 'lamar-lscpa')

    def test_resaved_deferred_row_keeps_its_campus(self):
        from mailer import send_html_mail
        from mailer.models import Message
        with in_campus('LAMAR_A'):
            send_html_mail('s', 'b', '<p>b</p>', DEFAULT_FROM, ['to@x.com'])
        row = Message.objects.latest('pk')
        with in_campus('LAMAR_B'):
            row.save()
        row.refresh_from_db()
        self.assertEqual(row.email.extra_headers['X-MyCE-Campus'], 'LAMAR_A')

    @override_settings(SES_CAMPUS_CONFIG=None)
    def test_single_campus_queue_untouched(self):
        from mailer import send_html_mail
        from mailer.models import Message
        with in_campus('EWU') as lookup:
            send_html_mail('s', 'b', '<p>b</p>', DEFAULT_FROM, ['to@x.com'])
        row = Message.objects.latest('pk')
        self.assertNotIn('X-MyCE-Campus', row.email.extra_headers)
        lookup.assert_not_called()


@override_settings(SES_CAMPUS_CONFIG=CONFIG)
class EventCampusTest(TestCase):
    def _event(self, tags):
        return SESEvent.objects.create(
            event_type='delivery', message_id=uuid.uuid4().hex, email='a@x.com',
            timestamp='2026-10-03T00:00:00Z',
            raw_message={'mail': {'tags': tags}})

    def test_campus_from_configuration_set_tag(self):
        event = self._event({'ses:configuration-set': ['lamar-lscpa']})
        self.assertEqual(event.campus_code, 'LAMAR_B')

    def test_unknown_set_leaves_blank(self):
        self.assertEqual(self._event({'ses:configuration-set': ['other']}).campus_code, '')

    def test_no_tags_leaves_blank(self):
        self.assertEqual(self._event({}).campus_code, '')
