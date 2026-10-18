"""Record each outgoing message as a SentEmail and tag it for SES.

Called from RoutingBackend.send_messages(), after routing and just before the
inner backend sends. The row's id travels to SES as the `myce-id` message tag
(X-SES-MESSAGE-TAGS), so SNS delivery/bounce/open events come back with it.

Every function here swallows its own errors: losing a log row is acceptable,
losing a message is not.
"""
import logging
import re
from email.utils import getaddresses

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import campus_mail
from .models import SentEmail, SentEmailRecipient

logger = logging.getLogger(__name__)

TAG_HEADER = 'X-SES-MESSAGE-TAGS'
TAG_NAME = 'myce-id'
FIELDS = ('to', 'cc', 'bcc')

# A sender sets this header to keep a message's bodies out of the log
# (one-time codes and the like). Internal: stripped before sending.
NO_BODY_HEADER = 'X-MyCE-No-Body-Log'

# Live credentials never go into the stored copy: anyone with
# view_sent_email can read it. Django's password-reset links
# (password_reset/<uidb64>/<token>/) are redacted by default; a tenant can
# add patterns with SES_TRACKING_BODY_REDACT_PATTERNS.
DEFAULT_REDACT_PATTERNS = (
    r'(password_reset|reset)/[A-Za-z0-9_\-]+/[A-Za-z0-9]{1,13}-[A-Za-z0-9]{20,}/?',
)
REDACTED = '[link removed]'


def snapshot(messages):
    """The recipients of each message before any routing touches them."""
    return [{f: list(getattr(m, f, None) or []) for f in FIELDS} for m in messages]


def _bare(addresses):
    return [address for _, address in getaddresses(list(addresses or [])) if address]


def _redact(body):
    if not body:
        return body
    patterns = tuple(DEFAULT_REDACT_PATTERNS) + tuple(
        getattr(settings, 'SES_TRACKING_BODY_REDACT_PATTERNS', ()) or ())
    for pattern in patterns:
        body = re.sub(pattern, REDACTED, body)
    return body


def _bodies(message):
    if getattr(message, 'content_subtype', '') == 'html':
        text, html = None, message.body
    else:
        text = message.body if isinstance(message.body, str) else None
        html = next((content for content, mimetype in getattr(message, 'alternatives', None) or []
                     if mimetype == 'text/html'), None)
    return _redact(text), _redact(html)


def _header(message, name):
    """Case-insensitive lookup of an extra header: (actual key, value)."""
    for key, value in message.extra_headers.items():
        if key.lower() == name.lower():
            return key, value
    return None, None


def _campus_code(message):
    code = message.extra_headers.get(campus_mail.CAMPUS_HEADER)
    if code:
        return code
    try:
        return campus_mail.current_campus_code() or ''
    except Exception:
        return ''


def _tag(message, row):
    """Set this row's myce-id tag, keeping other tags and replacing any
    myce-id left from an earlier send of the same message object."""
    key, existing = _header(message, TAG_HEADER)
    if key:
        del message.extra_headers[key]
    others = [pair.strip() for pair in (existing or '').split(',')
              if pair.strip() and not pair.strip().startswith(f'{TAG_NAME}=')]
    message.extra_headers[TAG_HEADER] = ', '.join(others + [f'{TAG_NAME}={row.id.hex}'])


def record(messages, originals, path, debug_flags=None):
    """Create one SentEmail per message and tag the message. None on failure."""
    rows = []
    for index, message in enumerate(messages):
        try:
            delivered = {f: _bare(getattr(message, f, None)) for f in FIELDS}
            original = {f: _bare(originals[index][f]) for f in FIELDS}
            everyone = {address.lower()
                        for group in (*delivered.values(), *original.values())
                        for address in group}
            key, _ = _header(message, NO_BODY_HEADER)
            if key:
                del message.extra_headers[key]
                text, html = None, None
                trackable = any(m == 'text/html' for _, m in getattr(message, 'alternatives', None) or []) \
                    or getattr(message, 'content_subtype', '') == 'html'
            else:
                text, html = _bodies(message)
                trackable = html is not None
            # A savepoint: a database error here must not abort the caller's
            # transaction (django-mailer sends inside atomic(); an aborted
            # transaction would re-queue mail that already went out).
            with transaction.atomic():
                row = SentEmail.objects.create(
                    original_to=original['to'], original_cc=original['cc'],
                    original_bcc=original['bcc'],
                    delivered_to=delivered['to'], delivered_cc=delivered['cc'],
                    delivered_bcc=delivered['bcc'],
                    search_addresses=' '.join(sorted(everyone)),
                    from_email=(message.from_email or '')[:320],
                    subject=(message.subject or '')[:998],
                    text_body=text, html_body=html,
                    path=path,
                    campus_code=_campus_code(message),
                    debug_routed=bool(debug_flags and debug_flags[index]),
                    sent_at=timezone.now(),
                    trackable=trackable,
                )
                SentEmailRecipient.objects.bulk_create(
                    [SentEmailRecipient(sent_email=row, address=address[:320])
                     for address in sorted(everyone)],
                    ignore_conflicts=True)
            _tag(message, row)
            rows.append(row)
        except Exception:
            logger.exception('Could not record an outgoing message')
            rows.append(None)
    return rows


def mark(rows, error=None):
    """Store the SMTP outcome on the rows of one inner send."""
    ids = [row.pk for row in rows if row is not None]
    if not ids:
        return
    try:
        with transaction.atomic():
            SentEmail.objects.filter(pk__in=ids).update(
                smtp_status=SentEmail.SMTP_FAILED if error else SentEmail.SMTP_SENT,
                smtp_error=str(error) if error else '')
    except Exception:
        logger.exception('Could not record the SMTP result')
