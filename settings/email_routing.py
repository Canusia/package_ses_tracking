"""
Settings page: which address(es) each role receives mail at.

Fields are generated from ``settings.MY_CE['roles']`` at construction time, so
a tenant that adds or comments out a role gets the matching field without a
code change here. Values are stored nested::

    {'mode': 'active', 'roles': {'instructor': ['secondary'], ...}}

`mode` is the kill switch. The stored value is read on every send batch by
``ses_tracking.routing.load_config``; see ``ses_tracking/routing.py`` for the
resolution semantics this configures.

Note the name collision hazard: this package is ``ses_tracking.settings`` while
``django.conf.settings`` is the Django settings object. Every module here
imports the latter as ``dj_settings``.
"""
from django import forms
from django.conf import settings as dj_settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse
from django.urls import reverse_lazy

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.models.settings import Setting

from ..routing import KIND_CHOICES, KIND_PRIMARY, SETTING_KEY

FIELD_PREFIX = 'role_'
DEBUG_PREFIX = 'debug_'
EVERYONE_ELSE = 'debug_everyone_else'


def _split(value):
    return [a.strip() for a in (value or '').replace(';', ',').split(',') if a.strip()]


def _clean_addresses(value):
    addresses = _split(value)
    bad = []
    for address in addresses:
        try:
            validate_email(address)
        except ValidationError:
            bad.append(address)
    if bad:
        raise ValidationError(f'Not valid email address(es): {", ".join(bad)}')
    return addresses


class SettingForm(forms.Form):

    mode = forms.ChoiceField(
        choices=(('active', 'Active'), ('inactive', 'Inactive')),
        required=True,
        label='Role Email Routing',
        help_text=(
            'When Active, mail addressed to a user is delivered to the '
            'address(es) selected for their role(s) below, and to nothing '
            'else. A user in several roles receives mail at the combination '
            'of all their roles\' selections. A user whose selected addresses '
            'are all blank keeps receiving mail at their primary address. '
            'This does not affect how anyone signs in.'
        ),
    )


def _roles():
    return (getattr(dj_settings, 'MY_CE', None) or {}).get('roles') or {}


def field_name(slug):
    return f'{FIELD_PREFIX}{slug}'


class email_routing(SettingForm):
    key = SETTING_KEY

    def __init__(self, request, *args, **kwargs):
        initial = kwargs.get('initial') or {}
        stored_roles = initial.get('roles') or {}
        stored_debug = initial.get('debug_lists') or {}

        super().__init__(*args, **kwargs)

        for slug, meta in _roles().items():
            name = field_name(slug)
            self.fields[name] = forms.MultipleChoiceField(
                choices=KIND_CHOICES,
                widget=forms.CheckboxSelectMultiple,
                # Not "empty == send this role nothing": routing.py treats an
                # empty kinds set as no configuration for that role and
                # leaves mail untouched (today's behavior), which is the
                # safe direction. See the help_text below and
                # routing.py's module docstring.
                required=False,
                label=meta.get('nice_name') or slug,
                help_text=(
                    'Clearing every box leaves this role\'s mail unchanged '
                    '-- it does NOT suppress delivery.'
                ),
            )
            self.initial.setdefault(
                name, stored_roles.get(slug, [KIND_PRIMARY]))

        # Staging debug routing (ses_tracking.debug_routing). The lists are
        # stored here, but only the deployment's environment switches them on.
        for slug, meta in _roles().items():
            name = f'{DEBUG_PREFIX}{slug}'
            self.fields[name] = forms.CharField(
                required=False,
                label=f"Debug list: {meta.get('nice_name') or slug}",
                help_text=('Comma-separated. Used only while debug routing is '
                           'switched on for this deployment (staging).'),
            )
            self.initial[name] = ', '.join(stored_debug.get(slug) or [])
        self.fields[EVERYONE_ELSE] = forms.CharField(
            required=False,
            label='Debug list: everyone else',
            help_text=('Comma-separated. While debug routing is on, mail for anyone '
                       'not covered above (parents, counselors, other addresses) '
                       'goes here. If empty, that mail is not sent.'),
        )
        # Overwrite, not setdefault: the stored value is a list under the
        # same key, and the field shows it comma-joined.
        self.initial[EVERYONE_ELSE] = ', '.join(initial.get('debug_everyone_else') or [])

        from ..debug_routing import is_on
        self.debug_routing_on = is_on()
        help_text = self.fields[EVERYONE_ELSE].help_text
        if self.debug_routing_on:
            help_text = ('Debug routing is ON for this deployment: all mail goes '
                         'to the debug lists. ' + help_text)
        elif stored_debug or initial.get('debug_everyone_else'):
            help_text = ('These debug lists are saved but inactive: debug routing '
                         'is off for this deployment. ' + help_text)
        self.fields[EVERYONE_ELSE].help_text = help_text

        self.request = request
        self.helper = FormHelper()
        self.helper.attrs = {'target': '_blank'}
        self.helper.form_method = 'POST'
        self.helper.form_action = reverse_lazy(
            'setting:run_record', args=[request.GET.get('report_id')])
        self.helper.add_input(Submit('submit', 'Save Setting'))

    def clean(self):
        data = super().clean()
        for name in [f'{DEBUG_PREFIX}{slug}' for slug in _roles()] + [EVERYONE_ELSE]:
            if name in self.errors:
                continue
            try:
                data[name] = _clean_addresses(data.get(name))
            except ValidationError as exc:
                self.add_error(name, exc)
        return data

    def _to_python(self):
        return {
            'mode': self.cleaned_data.get('mode', 'inactive'),
            'roles': {
                slug: list(self.cleaned_data.get(field_name(slug)) or [])
                for slug in _roles()
            },
            'debug_lists': {
                slug: self.cleaned_data[f'{DEBUG_PREFIX}{slug}']
                for slug in _roles() if self.cleaned_data.get(f'{DEBUG_PREFIX}{slug}')
            },
            'debug_everyone_else': self.cleaned_data.get(EVERYONE_ELSE) or [],
        }

    @classmethod
    def from_db(cls):
        try:
            return Setting.objects.get(key=cls.key).value
        except Setting.DoesNotExist:
            return {}
        except Exception:
            # Never let a settings lookup break outgoing mail.
            return {}

    def install(self):
        # Unlike most settings in MyCE, install() does NOT overwrite an
        # existing value: this decides where mail goes, and quietly resetting
        # it on a redeploy would be the wrong default.
        try:
            Setting.objects.get(key=self.key)
            return
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = {
            # Ships switched off deliberately: seeding 'active' is NOT inert.
            # build_routing_map rewrites every address a matched user owns,
            # not just the incoming one, so 'active' with every role at
            # ['primary'] would move mail addressed to a user's
            # secondary_email/alt_email onto their primary on day one, with
            # no CE action and nothing in the logs to say a config changed.
            'mode': 'inactive',
            # Every role to primary: once a CE admin switches mode to
            # 'active', nothing moves until a role is deliberately pointed
            # somewhere else.
            'roles': {slug: [KIND_PRIMARY] for slug in _roles()},
        }
        setting.save()

    def run_record(self):
        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = self._to_python()
        setting.save()

        return JsonResponse({
            'message': 'Successfully saved settings',
            'status': 'success'})
