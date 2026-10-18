"""Join SES events to the SentEmail they belong to.

SES copies every message tag onto each event as mail.tags; capture.py set
`myce-id` to the SentEmail's id when the message was sent.
"""
import logging
import uuid

from .models import SentEmail

logger = logging.getLogger(__name__)

STATUS_FOR_EVENT = {
    'delivery': 'delivered', 'bounce': 'bounced', 'complaint': 'complained',
    'reject': 'rejected', 'delivery_delay': 'delayed',
}


def sent_email_for(ses_message):
    try:
        values = ((ses_message or {}).get('mail') or {}).get('tags', {}).get('myce-id') or []
        value = values[0] if isinstance(values, list) else values
        return SentEmail.objects.filter(pk=uuid.UUID(hex=value)).first()
    except (AttributeError, IndexError, TypeError, ValueError):
        return None


def link(ses_event):
    """Attach `ses_event` to its SentEmail and update that row. Never raises."""
    try:
        row = sent_email_for(ses_event.raw_message)
        if row is None:
            return
        ses_event.sent_email = row
        ses_event.save(update_fields=['sent_email'])
        if ses_event.event_type == 'open':
            row.record_open(ses_event.timestamp)
        elif ses_event.event_type in STATUS_FOR_EVENT:
            row.advance(STATUS_FOR_EVENT[ses_event.event_type])
    except Exception:
        logger.exception('Could not link SES event %s', ses_event.pk)
