from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.mail import EmailMessage, get_connection
from django.test import TestCase, override_settings

from ses_tracking.backend import RoutingBackend, RoutingSESBackend

LOCMEM = 'django.core.mail.backends.locmem.EmailBackend'
ROUTING = 'ses_tracking.backend.RoutingBackend'


def _instructor(email, secondary):
    User = get_user_model()
    user = User.objects.create(username=email, email=email,
                               secondary_email=secondary)
    group, _ = Group.objects.get_or_create(name='instructor')
    user.groups.add(group)
    return user


def _config(mode='active', roles=None):
    return {'mode': mode,
            'roles': roles if roles is not None else {'instructor': ['secondary']}}


@override_settings(EMAIL_BACKEND=ROUTING, SES_TRACKING_ROUTING_INNER_BACKEND=LOCMEM)
class RoutingBackendTests(TestCase):

    def setUp(self):
        mail.outbox = []

    def _patch_config(self, config):
        from unittest.mock import patch
        p = patch('ses_tracking.backend.load_config', return_value=config)
        p.start()
        self.addCleanup(p.stop)

    def test_rewrites_the_to_list(self):
        _instructor('teach@college.edu', 'teach@home.com')
        self._patch_config(_config())
        EmailMessage('Subject', 'Body', 'from@x.com',
                     ['teach@college.edu']).send()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['teach@home.com'])

    def test_rewrites_cc_and_bcc(self):
        _instructor('teach@college.edu', 'teach@home.com')
        self._patch_config(_config())
        message = EmailMessage('S', 'B', 'from@x.com', ['other@x.com'],
                               cc=['teach@college.edu'],
                               bcc=['teach@college.edu'])
        message.send()
        self.assertEqual(mail.outbox[0].cc, ['teach@home.com'])
        self.assertEqual(mail.outbox[0].bcc, ['teach@home.com'])

    def test_inactive_mode_leaves_recipients_alone(self):
        _instructor('teach@college.edu', 'teach@home.com')
        self._patch_config(_config(mode='inactive'))
        EmailMessage('S', 'B', 'from@x.com', ['teach@college.edu']).send()
        self.assertEqual(mail.outbox[0].to, ['teach@college.edu'])

    def test_non_user_recipient_is_untouched(self):
        self._patch_config(_config())
        EmailMessage('S', 'B', 'from@x.com', ['stranger@x.com']).send()
        self.assertEqual(mail.outbox[0].to, ['stranger@x.com'])

    def test_collapses_the_dual_address_pattern(self):
        _instructor('teach@college.edu', 'teach@home.com')
        self._patch_config(_config())
        EmailMessage('S', 'B', 'from@x.com',
                     ['teach@home.com', 'teach@college.edu']).send()
        self.assertEqual(mail.outbox[0].to, ['teach@home.com'])

    def test_routing_failure_still_delivers_the_original(self):
        from unittest.mock import patch
        _instructor('teach@college.edu', 'teach@home.com')
        self._patch_config(_config())
        with patch('ses_tracking.backend.build_routing_map',
                   side_effect=RuntimeError('boom')):
            EmailMessage('S', 'B', 'from@x.com',
                         ['teach@college.edu']).send()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['teach@college.edu'])

    def test_one_config_load_per_batch(self):
        from unittest.mock import patch
        _instructor('teach@college.edu', 'teach@home.com')
        with patch('ses_tracking.backend.load_config',
                   return_value=_config()) as load:
            connection = get_connection(backend=ROUTING)
            connection.send_messages([
                EmailMessage('S', 'B', 'from@x.com', ['teach@college.edu']),
                EmailMessage('S', 'B', 'from@x.com', ['teach@college.edu']),
            ])
        self.assertEqual(load.call_count, 1)


class InnerBackendTests(TestCase):

    @override_settings(SES_TRACKING_ROUTING_INNER_BACKEND=LOCMEM)
    def test_routing_backend_uses_the_configured_inner(self):
        backend = RoutingBackend()
        self.assertEqual(
            f'{type(backend.connection).__module__}.'
            f'{type(backend.connection).__name__}',
            'django.core.mail.backends.locmem.EmailBackend',
        )

    @override_settings(SES_TRACKING_ROUTING_INNER_BACKEND=LOCMEM)
    def test_ses_variant_always_uses_the_ses_backend(self):
        backend = RoutingSESBackend()
        self.assertEqual(type(backend.connection).__name__, 'SESBackend')

    @override_settings(SES_TRACKING_ROUTING_INNER_BACKEND=ROUTING)
    def test_self_reference_falls_back_instead_of_recursing(self):
        backend = RoutingBackend()
        self.assertEqual(type(backend.connection).__name__, 'EmailBackend')
        self.assertIn('smtp', type(backend.connection).__module__)
