"""Staging debug routing: switched only by settings.SES_TRACKING_DEBUG_ROUTING,
per-role debug lists plus a required 'everyone else' list, fail closed
(sent-email spec §7)."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.mail import EmailMessage
from django.test import RequestFactory, TestCase, override_settings

from ses_tracking.models import SentEmail

LOCMEM = 'django.core.mail.backends.locmem.EmailBackend'
ROUTING = 'ses_tracking.backend.RoutingBackend'


def _user(email, *groups):
    user = get_user_model().objects.create(username=email, email=email)
    for g in groups:
        user.groups.add(Group.objects.get_or_create(name=g)[0])
    return user


CONFIG = {
    'mode': 'inactive', 'roles': {},
    'debug_lists': {'student': ['qa-students@canusia.com'],
                    'instructor': ['qa-instructors@canusia.com']},
    'debug_everyone_else': ['qa-other@canusia.com'],
}


@override_settings(EMAIL_BACKEND=ROUTING, SES_TRACKING_ROUTING_INNER_BACKEND=LOCMEM,
                   SES_TRACKING_DEBUG_ROUTING=True)
class DebugRoutingTests(TestCase):

    def setUp(self):
        mail.outbox = []
        self.config = dict(CONFIG)
        p = patch('ses_tracking.backend.load_config', side_effect=lambda: self.config)
        p.start()
        self.addCleanup(p.stop)

    def send(self, to, **kw):
        EmailMessage('Hello', 'b', 'f@x.com', to, **kw).send()
        return mail.outbox[-1] if mail.outbox else None

    def test_role_list_redirects(self):
        _user('stu@x.com', 'student')
        sent = self.send(['stu@x.com'])
        self.assertEqual(sent.to, ['qa-students@canusia.com'])
        self.assertTrue(sent.subject.startswith('[STAGING → stu@x.com] '))
        self.assertEqual(sent.extra_headers['X-MyCE-Original-To'], 'stu@x.com')
        row = SentEmail.objects.get()
        self.assertTrue(row.debug_routed)
        self.assertEqual(row.original_to, ['stu@x.com'])
        self.assertEqual(row.delivered_to, ['qa-students@canusia.com'])

    def test_user_in_several_roles_gets_the_union(self):
        _user('both@x.com', 'student', 'instructor')
        self.assertCountEqual(self.send(['both@x.com']).to,
                              ['qa-students@canusia.com', 'qa-instructors@canusia.com'])

    def test_non_user_goes_to_everyone_else(self):
        self.assertEqual(self.send(['parent@gmail.com']).to, ['qa-other@canusia.com'])

    def test_role_without_a_list_goes_to_everyone_else(self):
        _user('admin@x.com', 'highschool_admin')
        self.assertEqual(self.send(['admin@x.com']).to, ['qa-other@canusia.com'])

    def test_display_name_address_is_resolved(self):
        _user('stu@x.com', 'student')
        self.assertEqual(self.send(['"Stu Dent" <stu@x.com>']).to, ['qa-students@canusia.com'])

    def test_cc_and_bcc_are_rewritten_and_deduplicated(self):
        _user('stu@x.com', 'student')
        sent = self.send(['stu@x.com'], cc=['parent@gmail.com', 'dad@gmail.com'], bcc=['stu@x.com'])
        self.assertEqual(sent.cc, ['qa-other@canusia.com'])
        self.assertEqual(sent.bcc, ['qa-students@canusia.com'])

    def test_empty_everyone_else_drops_non_users(self):
        self.config['debug_everyone_else'] = []
        self.assertIsNone(self.send(['parent@gmail.com']))
        self.assertFalse(SentEmail.objects.exists())

    def test_unsaved_setting_drops_everything(self):
        self.config = {}
        with self.assertLogs('ses_tracking.debug_routing', 'WARNING'):
            self.assertIsNone(self.send(['anyone@x.com']))

    @override_settings(SES_TRACKING_DEBUG_ROUTING=False)
    def test_switch_off_leaves_mail_alone_even_with_lists_saved(self):
        _user('stu@x.com', 'student')
        sent = self.send(['stu@x.com'])
        self.assertEqual(sent.to, ['stu@x.com'])
        self.assertEqual(sent.subject, 'Hello')
        self.assertFalse(SentEmail.objects.get().debug_routed)


@override_settings(MY_CE={'roles': {'student': {'nice_name': 'Student'}}})
class DebugSettingFormTests(TestCase):

    def _form(self, data):
        from ses_tracking.settings.email_routing import email_routing
        return email_routing(RequestFactory().get('/?report_id=1'), data=data)

    def test_rejects_a_bad_address(self):
        form = self._form({'mode': 'inactive',
                           'debug_everyone_else': 'qa@canusia.com, not-an-email'})
        self.assertFalse(form.is_valid())
        self.assertIn('debug_everyone_else', form.errors)

    def test_saves_lists(self):
        form = self._form({'mode': 'inactive', 'debug_everyone_else': 'qa@canusia.com',
                           'debug_student': 'qa-s@canusia.com, qa-t@canusia.com'})
        self.assertTrue(form.is_valid(), form.errors)
        value = form._to_python()
        self.assertEqual(value['debug_everyone_else'], ['qa@canusia.com'])
        self.assertEqual(value['debug_lists'], {'student': ['qa-s@canusia.com', 'qa-t@canusia.com']})

    def test_initial_values_are_shown_back(self):
        from ses_tracking.settings.email_routing import email_routing
        form = email_routing(RequestFactory().get('/?report_id=1'), initial={
            'mode': 'inactive', 'roles': {},
            'debug_lists': {'student': ['a@x.com', 'b@x.com']},
            'debug_everyone_else': ['c@x.com']})
        self.assertEqual(form.initial['debug_student'], 'a@x.com, b@x.com')
        self.assertEqual(form.initial['debug_everyone_else'], 'c@x.com')


@override_settings(MY_CE={'roles': {'student': {'nice_name': 'Student'}}})
class DebugSettingNoticeTests(TestCase):

    def _form(self, initial=None):
        from ses_tracking.settings.email_routing import email_routing, EVERYONE_ELSE
        form = email_routing(RequestFactory().get('/?report_id=1'), initial=initial or {})
        return str(form.fields[EVERYONE_ELSE].help_text)

    @override_settings(SES_TRACKING_DEBUG_ROUTING=True)
    def test_notice_when_on(self):
        self.assertIn('Debug routing is ON for this deployment', self._form())

    def test_notice_when_off_with_saved_lists(self):
        self.assertIn('saved but inactive', self._form({'debug_everyone_else': ['qa@x.com']}))

    def test_no_notice_when_off_and_empty(self):
        text = self._form()
        self.assertNotIn('Debug routing is ON', text)
        self.assertNotIn('inactive', text)
