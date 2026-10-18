"""Sent Email API, for the CE page and the person Emails tab."""
import datetime

from rest_framework import viewsets

from .models import SentEmail
from .permissions import CanViewSentEmail
from .serializers import SentEmailDetailSerializer, SentEmailTableSerializer


def _person_filter(qs, value):
    """Rows sent to any of the comma-separated addresses: an exact, indexed
    lookup on SentEmailRecipient. A blank list matches nothing."""
    wanted = [a.strip().lower() for a in value.split(',') if a.strip()]
    if not wanted:
        return qs.none()
    return qs.filter(recipients__address__in=wanted).distinct()


class SentEmailViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CanViewSentEmail]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return SentEmailDetailSerializer
        return SentEmailTableSerializer

    def get_queryset(self):
        qs = SentEmail.objects.all()
        if self.action == 'retrieve':
            return qs.prefetch_related('events')

        qs = qs.defer('text_body', 'html_body')
        p = self.request.query_params
        if 'person' in p:
            qs = _person_filter(qs, p['person'])
        if p.get('address'):
            qs = qs.filter(search_addresses__contains=p['address'].strip().lower())
        if p.get('status'):
            qs = qs.filter(status=p['status'])
        opened = p.get('opened')
        if opened == 'yes':
            qs = qs.filter(first_opened_at__isnull=False)
        elif opened == 'no':
            qs = qs.filter(first_opened_at__isnull=True, trackable=True)
        elif opened == 'na':
            qs = qs.filter(trackable=False)
        if p.get('path'):
            qs = qs.filter(path=p['path'])
        if p.get('campus'):
            qs = qs.filter(campus_code=p['campus'])
        for name, lookup in (('start_date', 'gte'), ('end_date', 'lte')):
            try:
                day = datetime.date.fromisoformat(p.get(name) or '')
            except ValueError:
                continue
            qs = qs.filter(**{f'sent_at__date__{lookup}': day})
        return qs
