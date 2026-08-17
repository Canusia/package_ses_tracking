"""
Role-based recipient routing.
=============================

MyCE users can carry three addresses -- ``email`` (the institutional identity
they sign in with), ``secondary_email`` and ``alt_email``. Which of them mail
should actually be delivered to is a per-role policy: high school instructors
sign in with a college mailbox they never read, while staff want mail at the
primary address only.

Rather than editing the ~67 independent recipient-list builders in a MyCE
deployment -- several of which live in packages whose source a tenant does not
ship -- the swap happens once, at delivery time, in the mail backends in
``backend.py``. This module is the pure part: addresses in, rewrite map out.

Semantics (all four were explicit product decisions, not defaults):

* The configured kinds are the *delivery set*. An address whose kind is not
  selected is dropped, which is the only way to stop mail reaching an unread
  mailbox.
* A user's kinds are the *union* across every group they belong to.
* ``email`` is unique but ``secondary_email``/``alt_email`` are not; when an
  address matches several users the first wins.
* If the selected kinds resolve to nothing valid, the original address is left
  alone. Misconfiguration degrades to today's behavior instead of dropping mail.

Uses ``get_user_model()`` rather than importing cis, so the package stays
installable in a deployment that does not have cis.
"""
import logging

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Q
from django.db.models.functions import Lower

logger = logging.getLogger(__name__)

KIND_PRIMARY = 'primary'
KIND_SECONDARY = 'secondary'
KIND_ALT = 'alt'

# Ordered: resolved recipient lists follow this order for stable output.
KIND_FIELDS = {
    KIND_PRIMARY: 'email',
    KIND_SECONDARY: 'secondary_email',
    KIND_ALT: 'alt_email',
}

KIND_CHOICES = [
    (KIND_PRIMARY, 'Primary Email'),
    (KIND_SECONDARY, 'Secondary Email'),
    (KIND_ALT, 'Alternate Email'),
]

SETTING_KEY = 'ses_tracking.settings.email_routing'


def load_config():
    """The stored routing config, or ``{}`` if anything at all goes wrong.

    Called on every send batch, so it must never raise: a settings lookup
    failure has to cost us tracking, not mail.
    """
    try:
        from ses_tracking.settings.email_routing import email_routing
        return email_routing.from_db() or {}
    except Exception:
        logger.exception('Unable to load email routing config; routing disabled')
        return {}


def routing_is_active(config):
    """Absent config or absent mode means inactive -- fail to today's behavior."""
    return (config or {}).get('mode', 'inactive') == 'active'


def _is_valid(address):
    if not address:
        return False
    try:
        validate_email(address)
        return True
    except ValidationError:
        return False


def _configured_kinds(user, role_map):
    kinds = set()
    for group in user.groups.all():
        kinds.update(role_map.get(group.name) or [])
    return kinds


def _targets_for(user, kinds):
    """The user's addresses for `kinds`, in KIND_FIELDS order, deduped."""
    targets = []
    seen = set()
    for kind, field in KIND_FIELDS.items():
        if kind not in kinds:
            continue
        value = (getattr(user, field, '') or '').strip()
        if not _is_valid(value) or value.lower() in seen:
            continue
        seen.add(value.lower())
        targets.append(value)
    return targets


def build_routing_map(addresses, config):
    """``{lowercased incoming address: [addresses to deliver to]}``.

    Addresses absent from the returned map are left untouched by the caller --
    that covers non-users, users in unconfigured groups, and users whose
    selected fields are all blank or malformed.
    """
    wanted = {address.lower() for address in addresses if address}
    if not wanted:
        return {}

    role_map = (config or {}).get('roles') or {}
    if not role_map:
        return {}

    User = get_user_model()
    users = (
        User.objects
        .annotate(
            _primary=Lower('email'),
            _secondary=Lower('secondary_email'),
            _alt=Lower('alt_email'),
        )
        .filter(
            Q(_primary__in=wanted)
            | Q(_secondary__in=wanted)
            | Q(_alt__in=wanted)
        )
        .prefetch_related('groups')
        # Deterministic within each precedence class (see below); order
        # explicitly instead of relying on whatever Meta.ordering (or its
        # absence, on a cis-less deployment) happens to produce.
        .order_by('pk')
    )

    # An address can be one user's primary and another user's
    # secondary/alt -- a shared mailbox is the realistic case. Resolving by
    # raw pk order there would let whichever user has the lower pk hijack
    # mail addressed to the other user's primary. So primary-owners take
    # precedence over secondary/alt-owners; pk order is only the tie-break
    # within each of those two classes. Single query, still -- precedence is
    # resolved in Python over the rows already fetched.
    resolved_primary = {}
    resolved_other = {}
    for user in users:
        kinds = _configured_kinds(user, role_map)
        if not kinds:
            continue

        targets = _targets_for(user, kinds)
        if not targets:
            # Fallback: leave this user's mail where it was going.
            continue

        primary = (getattr(user, 'email', '') or '').strip().lower()
        for field in KIND_FIELDS.values():
            owned = (getattr(user, field, '') or '').strip().lower()
            if not owned or owned not in wanted:
                continue
            bucket = resolved_primary if owned == primary else resolved_other
            # First-match-wins within a precedence class.
            if owned not in bucket:
                bucket[owned] = targets

    return {**resolved_other, **resolved_primary}


def route_recipient_list(addresses, routing_map):
    """Rewrite one recipient list, preserving display names and order.

    Also drops blank entries: several call sites build
    ``[user.secondary_email, user.email]`` without checking the first for
    emptiness, pushing ``''`` into the list. De-duplication collapses those
    same dual-address lists once both resolve to the same target.
    """
    from email.utils import formataddr, getaddresses

    routed = []
    seen = set()

    for display_name, address in getaddresses(list(addresses)):
        if not address:
            continue

        # Unmatched addresses pass through unvalidated -- we never silently
        # drop mail we were not asked to touch.
        targets = routing_map.get(address.lower(), [address])

        for target in targets:
            if target.lower() in seen:
                continue
            seen.add(target.lower())
            routed.append(
                formataddr((display_name, target)) if display_name else target
            )

    return routed
