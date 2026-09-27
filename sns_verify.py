"""Verify that an SNS HTTP(S) message really came from AWS SNS (#2).

The webhook is public (csrf-exempt, no login), so without this anyone could
post forged SES events, or make the server fetch an arbitrary SubscribeURL.

Implements AWS's documented check: fetch the signing certificate -- only from
``https://sns.<region>.amazonaws.com`` -- and verify ``Signature`` over the
canonical string for the message type, SHA1 for SignatureVersion 1 and SHA256
for 2. Optionally restricts ``TopicArn`` to ``settings.SES_TRACKING_ALLOWED_TOPIC_ARNS``.
"""
import base64
import logging
import re
import urllib.request
from urllib.parse import urlparse

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from django.conf import settings

logger = logging.getLogger(__name__)

# sns.<region>.amazonaws.com, plus the China partition's .com.cn
_SNS_HOST = re.compile(r'^sns\.[a-z0-9-]+\.amazonaws\.com(\.cn)?$')

_SIGNED_KEYS = {
    'Notification': ('Message', 'MessageId', 'Subject', 'Timestamp', 'TopicArn', 'Type'),
    'SubscriptionConfirmation': ('Message', 'MessageId', 'SubscribeURL', 'Timestamp',
                                 'Token', 'TopicArn', 'Type'),
    'UnsubscribeConfirmation': ('Message', 'MessageId', 'SubscribeURL', 'Timestamp',
                                'Token', 'TopicArn', 'Type'),
}

_HASHES = {'1': hashes.SHA1, '2': hashes.SHA256}

_cert_cache = {}


class SNSVerificationError(Exception):
    """The message is not a genuine SNS message (or not one we accept)."""


def is_sns_url(url):
    """True for an https URL on sns.<region>.amazonaws.com -- nothing else."""
    try:
        parsed = urlparse(url or '')
    except ValueError:
        return False
    return parsed.scheme == 'https' and bool(_SNS_HOST.match(parsed.hostname or ''))


def canonical_string(message):
    """The string SNS signs: each signed key present in the message, as
    ``key\\nvalue\\n``, in the fixed order AWS documents for its type."""
    keys = _SIGNED_KEYS.get(message.get('Type'))
    if keys is None:
        raise SNSVerificationError(f"unsupported message type {message.get('Type')!r}")
    return ''.join(f'{k}\n{message[k]}\n' for k in keys if k in message)


def _fetch_cert(url):
    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310 -- URL checked by is_sns_url
        return resp.read()


def _certificate(url):
    if url not in _cert_cache:
        _cert_cache[url] = x509.load_pem_x509_certificate(_fetch_cert(url))
    return _cert_cache[url]


def verify(message):
    """Raise SNSVerificationError unless ``message`` is a genuine, accepted SNS message."""
    if not isinstance(message, dict):
        raise SNSVerificationError('message is not a JSON object')

    allowed_topics = getattr(settings, 'SES_TRACKING_ALLOWED_TOPIC_ARNS', None)
    if allowed_topics:
        if message.get('TopicArn') not in allowed_topics:
            raise SNSVerificationError(f"topic {message.get('TopicArn')!r} is not allowed")
    else:
        logger.warning('SES_TRACKING_ALLOWED_TOPIC_ARNS is not set; accepting any '
                       'correctly signed SNS topic (%s)', message.get('TopicArn'))

    hash_cls = _HASHES.get(str(message.get('SignatureVersion')))
    if hash_cls is None:
        raise SNSVerificationError(
            f"unsupported SignatureVersion {message.get('SignatureVersion')!r}")

    cert_url = message.get('SigningCertURL')
    if not is_sns_url(cert_url):
        raise SNSVerificationError(f'signing certificate URL {cert_url!r} is not on SNS')

    try:
        signature = base64.b64decode(message.get('Signature') or '', validate=True)
        _certificate(cert_url).public_key().verify(
            signature, canonical_string(message).encode('utf-8'),
            padding.PKCS1v15(), hash_cls())
    except SNSVerificationError:
        raise
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise SNSVerificationError(f'bad signature: {exc.__class__.__name__}') from exc
