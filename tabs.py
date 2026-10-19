"""Emails tab on person detail pages.

The tab registries live in each tenant's myce/component_registry, so every
import here is optional: a tenant without a registry simply doesn't get that
tab. Registered from SesTrackingConfig.ready().
"""
import importlib
import logging
from urllib.parse import quote

from django.urls import reverse

from .permissions import can_view_sent_email

logger = logging.getLogger(__name__)

REGISTRIES = (
    ('myce.component_registry.student', 'student_tabs'),
    ('myce.component_registry.teacher', 'teacher_tabs'),
    ('myce.component_registry.hs_administrator', 'hs_administrator_tabs'),
)


def _addresses(record):
    user = getattr(record, 'user', None) or record
    return [address for address in
            (getattr(user, field, '') for field in ('email', 'secondary_email', 'alt_email'))
            if address]


def emails_tab(request, record):
    person = quote(','.join(_addresses(record)), safe=',@')
    from .settings.sent_email import retention
    return {
        'api_url': f"{reverse('ses_tracking:sent-email-list')}?person={person}",
        'detail_url_template': reverse('ses_tracking:sent-email-detail', args=['ID']),
        'body_retention_days': retention()[0],
        'table_id': 'sent_email_' + str(record.pk).replace('-', ''),
    }


def _permission(user, record):
    return can_view_sent_email(user)


def register():
    for module_path, name in REGISTRIES:
        try:
            registry = getattr(importlib.import_module(module_path), name)
        except ModuleNotFoundError as exc:
            # The tenant has no such registry: no tab. Any other import error
            # is a real bug in the registry module, so it is logged.
            if exc.name and module_path.startswith(exc.name):
                continue
            logger.exception('Could not load the %s tab registry', module_path)
            continue
        except AttributeError:
            continue
        except Exception:
            logger.exception('Could not load the %s tab registry', module_path)
            continue
        registry.tab(slug='emails', title='Emails', order=95,
                     template='ses_tracking/sent_email/_tab.html',
                     permission=_permission)(emails_tab)
