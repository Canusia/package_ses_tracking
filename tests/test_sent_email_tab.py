"""Emails tab on person detail pages (sent-email spec §5)."""
from django.test import TestCase

from ses_tracking.models import SentEmail
from ses_tracking.tests.test_sent_email_access import API, _client, _rows, _user


class PersonFilterTests(TestCase):

    def setUp(self):
        from ses_tracking.models import SentEmailRecipient
        for subject, addresses in (('mine', ['a@x.com', 'b@y.com']),
                                   ('lookalike', ['aa@x.com']), ('blank', [])):
            row = SentEmail.objects.create(path='queue', subject=subject,
                                           search_addresses=' '.join(addresses))
            SentEmailRecipient.objects.bulk_create(
                [SentEmailRecipient(sent_email=row, address=a) for a in addresses])
        self.c = _client(_user('tab', perm=True))

    def subjects(self, person):
        return sorted(r['subject'] for r in _rows(
            self.c.get(API, {'format': 'json', 'person': person})))

    def test_exact_addresses_only(self):
        self.assertEqual(self.subjects('a@x.com'), ['mine'])

    def test_any_of_several_addresses(self):
        self.assertEqual(self.subjects('zz@q.com,b@y.com'), ['mine'])

    def test_blank_addresses_do_not_match_everything(self):
        self.assertEqual(self.subjects(',, '), [])


class TabRegistrationTests(TestCase):

    def test_registered_on_student_and_teacher(self):
        from myce.component_registry.student import student_tabs
        from myce.component_registry.teacher import teacher_tabs
        self.assertIn('emails', student_tabs._tabs)
        self.assertIn('emails', teacher_tabs._tabs)

    def test_hidden_without_permission(self):
        from myce.component_registry.student import student_tabs
        perm = student_tabs._tabs['emails']['permission']
        self.assertFalse(perm(_user('noperm'), None))
        self.assertTrue(perm(_user('yesperm', perm=True), None))

    def test_tab_context_lists_all_of_the_persons_addresses(self):
        from types import SimpleNamespace
        from ses_tracking.tabs import emails_tab
        user = SimpleNamespace(email='p@x.com', secondary_email='', alt_email='alt@y.com')
        ctx = emails_tab(None, SimpleNamespace(pk='abc', user=user))
        self.assertIn('person=p@x.com,alt@y.com', ctx['api_url'])


class TabRegistrationErrorTests(TestCase):

    def test_missing_registry_module_is_skipped_quietly(self):
        from unittest.mock import patch
        from ses_tracking import tabs
        with patch.object(tabs, 'REGISTRIES', (('myce.component_registry.nope', 'x_tabs'),)), \
                self.assertNoLogs('ses_tracking.tabs', level='ERROR'):
            tabs.register()

    def test_broken_registry_module_is_logged_not_hidden(self):
        from unittest.mock import patch
        from ses_tracking import tabs

        def broken(path):
            raise ImportError('cannot import name Thing from cis.models')

        with patch.object(tabs, 'REGISTRIES', (('myce.component_registry.student', 'student_tabs'),)), \
                patch('ses_tracking.tabs.importlib.import_module', side_effect=broken), \
                self.assertLogs('ses_tracking.tabs', level='ERROR'):
            tabs.register()


class FromColumnTests(TestCase):

    def test_table_has_a_searchable_from_column(self):
        from django.template.loader import render_to_string
        html = render_to_string('ses_tracking/sent_email/_table.html',
                                {'table_id': 't', 'api_url': '/x/'})
        self.assertIn('data-name="from_email"', html)
