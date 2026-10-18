"""Who may read sent mail: a CIS role AND ses_tracking.view_sent_email.

The permission is denied by default; superusers pass through has_perm.
"""
from rest_framework.permissions import BasePermission

PERM = 'ses_tracking.view_sent_email'


def can_view_sent_email(user):
    from cis.utils import user_has_cis_role
    return bool(user and user.is_authenticated and user_has_cis_role(user)
                and user.has_perm(PERM))


class CanViewSentEmail(BasePermission):
    def has_permission(self, request, view):
        return can_view_sent_email(request.user)
