from django.apps import apps as django_apps
from django.test import TestCase, RequestFactory, override_settings

from ses_tracking import routing


ROLES = {
    'instructor': {'nice_name': 'Instructor', 'icon': '', 'url': ''},
    'student': {'nice_name': 'Student', 'icon': '', 'url': ''},
}


def _request():
    request = RequestFactory().get('/?report_id=1')
    return request


def _setting_model():
    return django_apps.get_model('cis', 'Setting')


@override_settings(MY_CE={'roles': ROLES})
class EmailRoutingSettingTests(TestCase):

    def _form_class(self):
        from ses_tracking.settings.email_routing import email_routing
        return email_routing

    def test_one_field_per_configured_role(self):
        form = self._form_class()(_request())
        self.assertIn('role_instructor', form.fields)
        self.assertIn('role_student', form.fields)
        self.assertNotIn('role_faculty', form.fields)

    def test_role_field_is_labelled_with_nice_name(self):
        form = self._form_class()(_request())
        self.assertEqual(form.fields['role_instructor'].label, 'Instructor')

    def test_role_field_offers_the_three_kinds(self):
        form = self._form_class()(_request())
        self.assertEqual(
            list(form.fields['role_instructor'].choices), routing.KIND_CHOICES)

    def test_install_seeds_every_role_to_primary(self):
        self._form_class()(_request()).install()
        stored = self._form_class().from_db()
        self.assertEqual(stored['mode'], 'active')
        self.assertEqual(
            stored['roles'],
            {'instructor': ['primary'], 'student': ['primary']},
        )

    def test_install_does_not_overwrite_an_existing_value(self):
        Setting = _setting_model()
        Setting.objects.create(
            key=self._form_class().key,
            value={'mode': 'inactive', 'roles': {'instructor': ['secondary']}},
        )
        self._form_class()(_request()).install()
        self.assertEqual(
            self._form_class().from_db()['roles'],
            {'instructor': ['secondary']},
        )

    def test_from_db_returns_empty_dict_when_absent(self):
        self.assertEqual(self._form_class().from_db(), {})

    def test_initial_values_populate_the_dynamic_fields(self):
        initial = {'mode': 'active',
                   'roles': {'instructor': ['secondary', 'alt']}}
        form = self._form_class()(_request(), initial=initial)
        self.assertEqual(form.initial['role_instructor'], ['secondary', 'alt'])
        self.assertEqual(form.initial['role_student'], ['primary'])

    def test_to_python_nests_the_roles(self):
        form = self._form_class()(
            _request(),
            data={
                'mode': 'active',
                'role_instructor': ['secondary'],
                'role_student': ['primary', 'alt'],
            },
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form._to_python(),
            {'mode': 'active',
             'roles': {'instructor': ['secondary'],
                       'student': ['primary', 'alt']}},
        )

    def test_a_role_may_be_set_to_no_addresses(self):
        form = self._form_class()(
            _request(),
            data={'mode': 'active', 'role_instructor': [],
                  'role_student': ['primary']},
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form._to_python()['roles']['instructor'], [])

    def test_run_record_persists(self):
        form = self._form_class()(
            _request(),
            data={'mode': 'inactive', 'role_instructor': ['alt'],
                  'role_student': ['primary']},
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.run_record()
        stored = self._form_class().from_db()
        self.assertEqual(stored['mode'], 'inactive')
        self.assertEqual(stored['roles']['instructor'], ['alt'])

    def test_configurator_is_declared_on_the_app_config(self):
        from ses_tracking.apps import SesTrackingConfig
        names = [c['name'] for c in SesTrackingConfig.CONFIGURATORS]
        self.assertIn('email_routing', names)
        entry = next(c for c in SesTrackingConfig.CONFIGURATORS
                     if c['name'] == 'email_routing')
        self.assertEqual(entry['app'], 'ses_tracking')
