"""Record each outgoing message as a SentEmail and tag it for SES.

Called from RoutingBackend.send_messages(), after routing and just before the
inner backend sends. The row's id travels to SES as the `myce-id` message tag
(X-SES-MESSAGE-TAGS), so SNS delivery/bounce/open events come back with it.

Every function here swallows its own errors: losing a log row is acceptable,
losing a message is not.
"""
import logging
from email.utils import getaddresses

from django.utils import timezone

from . import campus_mail
from .models import SentEmail

logger = logging.getLogger(__name__)

TAG_HEADER = 'X-SES-MESSAGE-TAGS'
TAG_NAME = 'myce-id'
FIELDS = ('to', 'cc', 'bcc')


def snapshot(messages):
    """The recipients of each message before any routing touches them."""
    return [{f: list(getattr(m, f, None) or []) for f in FIELDS} for m in messages]


def _bare(addresses):
    return [address for _, address in getaddresses(list(addresses or [])) if address]


def _bodies(message):
    if getattr(message, 'content_subtype', '') == 'html':
        return None, message.body
    text = message.body if isinstance(message.body, str) else None
    html = next((content for content, mimetype in getattr(message, 'alternatives', None) or []
                 if mimetype == 'text/html'), None)
    return text, html


def _campus_code(message):
    code = message.extra_headers.get(campus_mail.CAMPUS_HEADER)
    if code:
        return code
    try:
        return campus_mail.current_campus_code() or ''
    except Exception:
        return ''


def _tag(message, row):
    headers = message.extra_headers
    existing = headers.get(TAG_HEADER, '')
    tag = f'{TAG_NAME}={row.id.hex}'
    headers[TAG_HEADER] = f'{existing}, {tag}' if existing else tag


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
            text, html = _bodies(message)
            row = SentEmail.objects.create(
                original_to=original['to'], original_cc=original['cc'],
                original_bcc=original['bcc'],
                delivered_to=delivered['to'], delivered_cc=delivered['cc'],
                delivered_bcc=delivered['bcc'],
                search_addresses=' '.join(sorted(everyone)),
                from_email=message.from_email or '',
                subject=(message.subject or '')[:998],
                text_body=text, html_body=html,
                path=path,
                campus_code=_campus_code(message),
                debug_routed=bool(debug_flags and debug_flags[index]),
                sent_at=timezone.now(),
                trackable=html is not None,
            )
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
        SentEmail.objects.filter(pk__in=ids).update(
            smtp_status=SentEmail.SMTP_FAILED if error else SentEmail.SMTP_SENT,
            smtp_error=str(error) if error else '')
    except Exception:
        logger.exception('Could not record the SMTP result')
