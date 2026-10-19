"""Staging debug routing.

While ``settings.SES_TRACKING_DEBUG_ROUTING`` is on, every recipient of every
outgoing message is replaced: a user goes to the debug lists of their roles
(the union, if several), and anyone else -- non-users, roles without a list --
goes to the required "everyone else" list.

The switch is the environment, never the database: each tenant sets it from
``EMAIL_DEBUG_ROUTING`` in its staging and preview manifests. Databases are
copied between production and staging, so a database switch could turn
redirection on in production, or quietly off in staging.

Fails closed: a recipient with nothing to go to is dropped and logged, never
delivered to the real address.
"""
import logging
from email.utils import getaddresses

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.db.models.functions import Lower

logger = logging.getLogger(__name__)

FIELDS = ('to', 'cc', 'bcc')
SUBJECT_PREFIX = '[STAGING → {}] '
ORIGINAL_HEADER = 'X-MyCE-Original-To'


def is_on():
    return bool(getattr(settings, 'SES_TRACKING_DEBUG_ROUTING', False))


def _users_by_address(addresses):
    """{lower-cased address: user}; a primary-address owner wins, then lowest pk."""
    wanted = {address.lower() for address in addresses if address}
    if not wanted:
        return {}
    users = (
        get_user_model().objects
        .annotate(_p=Lower('email'), _s=Lower('secondary_email'), _a=Lower('alt_email'))
        .filter(Q(_p__in=wanted) | Q(_s__in=wanted) | Q(_a__in=wanted))
        .prefetch_related('groups')
        .order_by('pk')
    )
    primary, other = {}, {}
    for user in users:
        own_primary = (user.email or '').lower()
        for field in ('email', 'secondary_email', 'alt_email'):
            owned = (getattr(user, field, '') or '').lower()
            if owned and owned in wanted:
                (primary if owned == own_primary else other).setdefault(owned, user)
    return {**other, **primary}


def _targets(address, users, lists, everyone_else):
    user = users.get(address.lower())
    targets = []
    if user is not None:
        for group in user.groups.all():
            targets.extend(lists.get(group.name) or [])
    return targets or list(everyone_else)


def apply(messages, config):
    """Rewrite every message's recipients in place; return per-message flags."""
    if not is_on():
        return [False] * len(messages)

    config = config or {}
    if 'debug_everyone_else' not in config and 'debug_lists' not in config:
        logger.warning('Debug routing is on but its lists were never saved: dropping all mail')
    lists = config.get('debug_lists') or {}
    everyone_else = config.get('debug_everyone_else') or []

    users = _users_by_address([
        address for message in messages for field in FIELDS
        for _, address in getaddresses(list(getattr(message, field, None) or []))])

    for message in messages:
        originals = [a for _, a in getaddresses(list(message.to or [])) if a]
        for field in FIELDS:
            routed, seen = [], set()
            for _, address in getaddresses(list(getattr(message, field, None) or [])):
                if not address:
                    continue
                targets = _targets(address, users, lists, everyone_else)
                if not targets:
                    logger.warning('Debug routing: dropped %s (no debug address)', address)
                for target in targets:
                    if target.lower() not in seen:
                        seen.add(target.lower())
                        routed.append(target)
            setattr(message, field, routed)
        # A custom To/Cc header overrides the rendered header: drop it so the
        # message shows who it actually went to.
        for key in [k for k in message.extra_headers if k.lower() in ('to', 'cc')]:
            del message.extra_headers[key]
        message.subject = (SUBJECT_PREFIX.format(originals[0] if originals else '?')
                           + (message.subject or ''))
        message.extra_headers[ORIGINAL_HEADER] = ', '.join(originals)
    return [True] * len(messages)
