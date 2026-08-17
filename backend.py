from django.conf import settings
import logging

logger = logging.getLogger(__name__)

from django.core.mail.backends.smtp import EmailBackend as SMTPBackend

from email.utils import getaddresses

from django.core.mail import get_connection
from django.core.mail.backends.base import BaseEmailBackend

from .routing import (
    build_routing_map,
    load_config,
    route_recipient_list,
    routing_is_active,
)

class SESBackend(SMTPBackend):
    """
    Custom email backend that wraps SMTP backend and adds SES configuration set header
    for tracking bounces/complaints.
    """
    
    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        
        # Get SES settings from Django settings
        self.aws_region = getattr(settings, 'AWS_SES_REGION', 'us-east-1')
        self.configuration_set = getattr(settings, 'AWS_SES_CONFIGURATION_SET', 'rmu-config-set')
    
    def _send(self, email_message):
        # Add configuration set header
        if not hasattr(email_message, 'extra_headers'):
            email_message.extra_headers = {}
        
        email_message.extra_headers['X-SES-CONFIGURATION-SET'] = self.configuration_set
        
        # Call the original _send method of the parent SMTP backend
        return super()._send(email_message)


SELF_PATHS = {
    'ses_tracking.backend.RoutingBackend',
    'ses_tracking.backend.RoutingSESBackend',
}
FALLBACK_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
SES_BACKEND_PATH = 'ses_tracking.backend.SESBackend'


class RoutingBackend(BaseEmailBackend):
    """Rewrites recipients per role, then delegates to an inner backend.

    The inner backend is named by ``SES_TRACKING_ROUTING_INNER_BACKEND``. Wire
    this class as ``EMAIL_BACKEND`` with the inner set to whatever the
    deployment used before, so direct ``django.core.mail`` sends get routed
    without changing how they are delivered.

    Routing must never cost a message: any failure is logged and the originals
    are delivered untouched.
    """

    RECIPIENT_FIELDS = ('to', 'cc', 'bcc')

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently)

        inner = self.inner_backend_path()
        if inner in SELF_PATHS:
            logger.error(
                'Routing inner backend points at a routing backend (%s); '
                'falling back to %s', inner, FALLBACK_BACKEND
            )
            inner = FALLBACK_BACKEND

        self.connection = get_connection(
            backend=inner, fail_silently=fail_silently, **kwargs
        )

    def inner_backend_path(self):
        return getattr(
            settings, 'SES_TRACKING_ROUTING_INNER_BACKEND', FALLBACK_BACKEND
        )

    def open(self):
        return self.connection.open()

    def close(self):
        return self.connection.close()

    def send_messages(self, email_messages):
        try:
            self.route(email_messages)
        except Exception:
            logger.exception(
                'Email routing failed; delivering messages unrouted'
            )

        return self.connection.send_messages(email_messages)

    def route(self, email_messages):
        """Rewrite recipients in place across the whole batch.

        Config and the routing map are resolved once per batch, not per
        message -- that is what keeps the added cost to a single extra query
        alongside the user lookup.
        """
        if not email_messages:
            return

        config = load_config()
        if not routing_is_active(config):
            return

        # Parsed with getaddresses, not taken raw: build_routing_map matches
        # whole strings, so a 'Jane <j@x.com>' entry would never match.
        addresses = []
        for message in email_messages:
            for field in self.RECIPIENT_FIELDS:
                addresses.extend(
                    address for _, address in
                    getaddresses(list(getattr(message, field, None) or []))
                )

        routing_map = build_routing_map(addresses, config)
        if not routing_map:
            return

        for message in email_messages:
            rewrites = []

            for field in self.RECIPIENT_FIELDS:
                current = getattr(message, field, None)
                if not current:
                    continue

                routed = route_recipient_list(current, routing_map)
                if routed == list(current):
                    continue

                setattr(message, field, routed)
                rewrites.append(f'{field}={routed} (was {list(current)})')

            if rewrites:
                # django-mailer logs the recipient recorded at *enqueue* time,
                # which is the pre-routing address -- stale by the time we get
                # here. This is the record of where mail actually went.
                logger.info(
                    'email routing: %s | %s',
                    message.subject, '; '.join(rewrites)
                )


class RoutingSESBackend(RoutingBackend):
    """Routing wrapper whose inner backend is always :class:`SESBackend`.

    Wire this as ``MAILER_EMAIL_BACKEND``. Using the plain
    :class:`RoutingBackend` there would send queued mail through the generic
    inner backend and silently drop the ``X-SES-CONFIGURATION-SET`` header,
    which is what bounce and complaint tracking depends on.
    """

    def inner_backend_path(self):
        return SES_BACKEND_PATH