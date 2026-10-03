"""Per-campus default sender and SES configuration set (#3).

Multi-campus deployments send each campus's mail from its own default sender
and through its own configuration set, so bounces and complaints are tracked
per college::

    SES_CAMPUS_CONFIG = {
        'LAMAR_A': {'from_email': 'noreply@lit.edu', 'configuration_set': 'lamar-lit'},
        'LAMAR_B': {'from_email': 'noreply@lamarpa.edu', 'configuration_set': 'lamar-lscpa'},
    }

The campus is known when mail is *created* (a request on that campus's host, or
a ``run_for_each_campus`` job) but not when the django-mailer queue is flushed.
So mail is **stamped** with ``X-MyCE-Campus`` at creation and **resolved** at
delivery, and the header is stripped before it reaches SMTP.

With ``SES_CAMPUS_CONFIG`` unset or empty, nothing is stamped and the campus is
never looked up, so single-campus tenants pay nothing and see no change.
"""
import logging
from email.utils import formataddr, parseaddr

from django.conf import settings

logger = logging.getLogger(__name__)

CAMPUS_HEADER = 'X-MyCE-Campus'
CONFIG_SET_HEADER = 'X-SES-CONFIGURATION-SET'


def campus_config():
    return getattr(settings, 'SES_CAMPUS_CONFIG', None) or {}


def campus_mail_config(campus_code):
    """``{'from_email': ..., 'configuration_set': ...}`` for a campus, or ``{}``."""
    if not campus_code:
        return {}
    return campus_config().get(campus_code) or {}


def default_configuration_set():
    """``AWS_SES_CONFIGURATION_SET``, or None. There is no implicit fallback."""
    return getattr(settings, 'AWS_SES_CONFIGURATION_SET', None) or None


def campus_for_configuration_set(configuration_set):
    """Reverse lookup used to tag SES events with their campus."""
    if not configuration_set:
        return ''
    for code, cfg in campus_config().items():
        if (cfg or {}).get('configuration_set') == configuration_set:
            return code
    return ''


def current_campus_code():
    """The active campus's code, or None. Soft dependency on cis."""
    try:
        from cis.campus_context import current_campus_or_none
    except Exception:
        return None
    try:
        campus = current_campus_or_none()
    except Exception:
        logger.exception('Could not resolve the current campus for outgoing mail')
        return None
    return getattr(campus, 'code', None) or None


def _headers(message):
    headers = getattr(message, 'extra_headers', None)
    if headers is None:
        headers = {}
        message.extra_headers = headers
    return headers


def stamp(message):
    """Record the creating campus on a message. Never overwrites an existing stamp."""
    if not campus_config():
        return
    headers = _headers(message)
    if headers.get(CAMPUS_HEADER):
        return
    code = current_campus_code()
    if code:
        headers[CAMPUS_HEADER] = code


def resolve(message):
    """Apply the campus sender, strip the internal header, return the campus config.

    Falls back to the current campus when the message was never stamped (a
    direct send straight to SESBackend inside a campus context).
    """
    headers = _headers(message)
    code = headers.pop(CAMPUS_HEADER, None)
    if not code and campus_config():
        code = current_campus_code()
    cfg = campus_mail_config(code)

    campus_from = cfg.get('from_email')
    if campus_from:
        name, address = parseaddr(message.from_email or '')
        _, default_address = parseaddr(getattr(settings, 'DEFAULT_FROM_EMAIL', '') or '')
        # Only the deployment default is swapped; an explicit sender (a
        # support-ticket type, an MOU from_address) is the caller's choice.
        if address and default_address and address.lower() == default_address.lower():
            message.from_email = formataddr((name, campus_from)) if name else campus_from
    return cfg


def configuration_set_for(cfg):
    return cfg.get('configuration_set') or default_configuration_set()


def stamp_queued_message(sender, instance, **kwargs):
    """pre_save on mailer.models.Message: stamp mail when it is enqueued.

    Enqueue runs inside the campus context; the flush does not. Deferred rows
    re-saved later keep their original stamp. Note django-mailer's DbBackend
    enqueues with bulk_create (no signals); mail reaching it through
    RoutingBackend is already stamped there.
    """
    if instance.pk or not campus_config():
        return
    try:
        email = instance.email
        if email is None:
            return
        before = dict(getattr(email, 'extra_headers', None) or {})
        stamp(email)
        if email.extra_headers != before:
            instance.email = email
    except Exception:
        logger.exception('Could not stamp the campus on a queued message')
