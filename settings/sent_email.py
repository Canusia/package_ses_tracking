"""
Settings page: how long sent mail is kept.

Read by ``manage.py prune_sent_email`` (scheduled daily through the cis
CronTab). Stored as ``{'body_retention_days': int, 'log_retention_days': int}``.
"""
from django import forms
from django.http import JsonResponse
from django.urls import reverse_lazy

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.models.settings import Setting

KEY = 'ses_tracking.settings.sent_email'
DEFAULTS = {'body_retention_days': 180, 'log_retention_days': 730}


def retention():
    """(body days, record days), falling back to the defaults."""
    value = sent_email.from_db() or {}
    return (int(value.get('body_retention_days') or DEFAULTS['body_retention_days']),
            int(value.get('log_retention_days') or DEFAULTS['log_retention_days']))


class sent_email(forms.Form):
    key = KEY

    body_retention_days = forms.IntegerField(
        min_value=1, label='Keep message bodies for (days)',
        help_text=('After this, the Sent Email page still shows who it went to, when, '
                   'and whether it was delivered or opened, but not the message itself.'))
    log_retention_days = forms.IntegerField(
        min_value=1, label='Keep sent email records for (days)')

    def __init__(self, request, *args, **kwargs):
        initial = dict(DEFAULTS)
        initial.update(kwargs.get('initial') or {})
        kwargs['initial'] = initial
        super().__init__(*args, **kwargs)
        self.request = request
        self.helper = FormHelper()
        self.helper.attrs = {'target': '_blank'}
        self.helper.form_method = 'POST'
        self.helper.form_action = reverse_lazy(
            'setting:run_record', args=[request.GET.get('report_id')])
        self.helper.add_input(Submit('submit', 'Save Setting'))

    def clean(self):
        data = super().clean()
        body, log = data.get('body_retention_days'), data.get('log_retention_days')
        if body and log and body > log:
            raise forms.ValidationError(
                'Message bodies cannot be kept longer than the records themselves.')
        return data

    @classmethod
    def from_db(cls):
        try:
            return Setting.objects.get(key=cls.key).value
        except Exception:
            return {}

    def install(self):
        # Never overwrite a tenant's saved retention on redeploy.
        Setting.objects.get_or_create(key=self.key, defaults={'value': dict(DEFAULTS)})

    def run_record(self):
        Setting.objects.update_or_create(key=self.key, defaults={'value': {
            name: self.cleaned_data[name] for name in DEFAULTS}})
        return JsonResponse({'message': 'Successfully saved settings', 'status': 'success'})
