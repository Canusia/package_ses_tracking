
# ses_tracking/views.py
import json
import logging
from django.utils import timezone
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import SESEvent
import boto3
from django.conf import settings

from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.db.models import Sum, Avg, Q
from datetime import datetime, timedelta
from .models import DailyEmailStats, SESEvent
from .serializers import DailyEmailStatsSerializer, DailyEmailStatsSummarySerializer, SESEventSerializer

logger = logging.getLogger(__name__)

class DataTablesPagination(PageNumberPagination):
    """
    Custom pagination for DataTables
    Handles draw, start, length parameters from DataTables
    """
    page_size_query_param = 'length'
    page_size = 10
    max_page_size = 100
    
    def get_paginated_response(self, data):
        request = self.request
        draw = int(request.query_params.get('draw', 1))
        
        return Response({
            'draw': draw,
            'recordsTotal': self.page.paginator.count,
            'recordsFiltered': self.page.paginator.count,
            'data': data
        })

class SESEventViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing SES Events (bounces and complaints)
    Optimized for DataTables integration.
    """
    queryset = SESEvent.objects.filter(
        Q(event_type='bounce') | Q(event_type='complaint')
    ).select_related().order_by('-timestamp')
    serializer_class = SESEventSerializer
    pagination_class = DataTablesPagination
    
    def get_queryset(self):
        """
        Custom queryset with search and filtering for DataTables
        """
        queryset = SESEvent.objects.filter(
            Q(event_type='bounce') | Q(event_type='complaint')
        ).order_by('-timestamp')
        
        # Handle DataTables search
        search_value = self.request.query_params.get('search[value]', '')
        if search_value:
            queryset = queryset.filter(
                Q(email__icontains=search_value) |
                Q(email_to__icontains=search_value) |
                Q(email_subject__icontains=search_value) |
                Q(bounce_type__icontains=search_value)
            )
        
        # Handle DataTables ordering
        order_column = self.request.query_params.get('order[0][column]')
        order_dir = self.request.query_params.get('order[0][dir]', 'desc')
        
        if order_column:
            columns = [
                'timestamp',
                'email',
                'email_subject',
                'email_to',
                'event_type',
                'bounce_type',
            ]
            
            try:
                column_index = int(order_column)
                if 0 <= column_index < len(columns):
                    order_field = columns[column_index]
                    if order_dir == 'desc':
                        order_field = f'-{order_field}'
                    queryset = queryset.order_by(order_field)
            except (ValueError, IndexError):
                pass
        
        # Filter by event type
        event_type = self.request.query_params.get('event_type')
        if event_type:
            queryset = queryset.filter(event_type=event_type)
        
        # Custom date range filtering
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        
        if start_date:
            try:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                queryset = queryset.filter(timestamp__date__gte=start_date)
            except ValueError:
                pass
        
        if end_date:
            try:
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
                queryset = queryset.filter(timestamp__date__lte=end_date)
            except ValueError:
                pass
        
        return queryset
    
    def list(self, request, *args, **kwargs):
        """
        Override list to handle DataTables pagination properly
        """
        queryset = self.filter_queryset(self.get_queryset())
        
        # Handle DataTables pagination
        start = int(request.query_params.get('start', 0))
        length = int(request.query_params.get('length', 10))
        
        if length > 0:
            page = (start // length) + 1
            request.query_params._mutable = True
            request.query_params['page'] = page
            request.query_params['length'] = length
            request.query_params._mutable = False
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)



class DailyEmailStatsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing daily email statistics.
    Optimized for DataTables integration.
    
    Provides:
    - list: Get all daily stats (DataTables compatible)
    - retrieve: Get specific day stats
    - summary: Get lightweight summary
    - date_range: Get stats for a date range
    - aggregate: Get aggregated totals for a period
    """
    queryset = DailyEmailStats.objects.all()
    serializer_class = DailyEmailStatsSerializer
    pagination_class = DataTablesPagination
    ordering = ['-date']  # Default ordering by date descending
    
    def get_queryset(self):
        """
        Custom queryset with search and filtering for DataTables
        """
        queryset = DailyEmailStats.objects.all()
        
        # Handle DataTables search
        search_value = self.request.query_params.get('search[value]', '')
        if search_value:
            queryset = queryset.filter(
                Q(date__icontains=search_value)
            )
        
        # Handle DataTables ordering
        order_column = self.request.query_params.get('order[0][column]')
        order_dir = self.request.query_params.get('order[0][dir]', 'desc')
        
        if order_column:
            columns = [
                'date',
                'total_sends', 
                'total_deliveries',
                'total_bounces',
                'total_complaints',
                'bounce_rate',
                'complaint_rate',
                'delivery_rate',
                'unique_recipients'
            ]
            
            try:
                column_index = int(order_column)
                if 0 <= column_index < len(columns):
                    order_field = columns[column_index]
                    if order_dir == 'desc':
                        order_field = f'-{order_field}'
                    queryset = queryset.order_by(order_field)
            except (ValueError, IndexError):
                pass
        else:
            # Default ordering
            queryset = queryset.order_by('-date')
        
        # Custom date range filtering
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        
        if start_date:
            try:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                queryset = queryset.filter(date__gte=start_date)
            except ValueError:
                pass
        
        if end_date:
            try:
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
                queryset = queryset.filter(date__lte=end_date)
            except ValueError:
                pass
        
        return queryset
    
    def get_serializer_class(self):
        """Use summary serializer for summary action"""
        if self.action == 'summary':
            return DailyEmailStatsSummarySerializer
        return DailyEmailStatsSerializer
    
    def list(self, request, *args, **kwargs):
        """
        Override list to handle DataTables pagination properly
        """
        queryset = self.filter_queryset(self.get_queryset())
        
        # Handle DataTables pagination
        start = int(request.query_params.get('start', 0))
        length = int(request.query_params.get('length', 10))
        
        if length > 0:
            page = (start // length) + 1
            request.query_params._mutable = True
            request.query_params['page'] = page
            request.query_params['length'] = length
            request.query_params._mutable = False
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """
        Get lightweight summary of recent stats
        Query params:
        - days: Number of recent days (default: 7)
        
        Example: /api/ses-stats/summary/?days=30
        """
        days = int(request.query_params.get('days', 7))
        start_date = datetime.now().date() - timedelta(days=days)
        
        queryset = self.queryset.filter(date__gte=start_date).order_by('-date')
        serializer = self.get_serializer(queryset, many=True)
        
        return Response({
            'period': f'Last {days} days',
            'start_date': start_date,
            'end_date': datetime.now().date(),
            'stats': serializer.data
        })
    
    @action(detail=False, methods=['get'])
    def date_range(self, request):
        """
        Get stats for a specific date range
        Query params:
        - start_date: Start date (YYYY-MM-DD) - required
        - end_date: End date (YYYY-MM-DD) - required
        
        Example: /api/ses-stats/date_range/?start_date=2025-11-01&end_date=2025-11-07
        """
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        if not start_date or not end_date:
            return Response(
                {'error': 'Both start_date and end_date are required (YYYY-MM-DD)'},
                status=400
            )
        
        try:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        except ValueError:
            return Response(
                {'error': 'Invalid date format. Use YYYY-MM-DD'},
                status=400
            )
        
        queryset = self.queryset.filter(date__gte=start_date, date__lte=end_date).order_by('-date')
        serializer = self.get_serializer(queryset, many=True)
        
        return Response({
            'start_date': start_date,
            'end_date': end_date,
            'count': queryset.count(),
            'stats': serializer.data
        })
    
    @action(detail=False, methods=['get'])
    def aggregate(self, request):
        """
        Get aggregated totals for a period
        Query params:
        - start_date: Start date (YYYY-MM-DD) - optional (defaults to 30 days ago)
        - end_date: End date (YYYY-MM-DD) - optional (defaults to today)
        
        Example: /api/ses-stats/aggregate/?start_date=2025-11-01&end_date=2025-11-07
        """
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        if not start_date:
            start_date = (datetime.now().date() - timedelta(days=30))
        else:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        
        if not end_date:
            end_date = datetime.now().date()
        else:
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        queryset = self.queryset.filter(date__gte=start_date, date__lte=end_date)
        
        # Calculate aggregates
        totals = queryset.aggregate(
            total_sends=Sum('total_sends'),
            total_deliveries=Sum('total_deliveries'),
            total_bounces=Sum('total_bounces'),
            total_complaints=Sum('total_complaints'),
            total_rejects=Sum('total_rejects'),
            total_rendering_failures=Sum('total_rendering_failures'),
            total_delivery_delays=Sum('total_delivery_delays'),
            permanent_bounces=Sum('permanent_bounces'),
            transient_bounces=Sum('transient_bounces'),
            avg_bounce_rate=Avg('bounce_rate'),
            avg_complaint_rate=Avg('complaint_rate'),
            avg_delivery_rate=Avg('delivery_rate'),
        )
        
        # Calculate overall rates from totals
        if totals['total_sends'] and totals['total_sends'] > 0:
            overall_bounce_rate = (totals['total_bounces'] / totals['total_sends']) * 100
            overall_complaint_rate = (totals['total_complaints'] / totals['total_sends']) * 100
            overall_delivery_rate = (totals['total_deliveries'] / totals['total_sends']) * 100
        else:
            overall_bounce_rate = 0
            overall_complaint_rate = 0
            overall_delivery_rate = 0
        
        return Response({
            'period': {
                'start_date': start_date,
                'end_date': end_date,
                'days': (end_date - start_date).days + 1
            },
            'totals': {
                **totals,
                'overall_bounce_rate': round(overall_bounce_rate, 2),
                'overall_complaint_rate': round(overall_complaint_rate, 2),
                'overall_delivery_rate': round(overall_delivery_rate, 2),
            }
        })
    
    @action(detail=False, methods=['get'])
    def latest(self, request):
        """
        Get the most recent daily stats
        
        Example: /api/ses-stats/latest/
        """
        try:
            latest_stat = self.queryset.latest('date')
            serializer = self.get_serializer(latest_stat)
            return Response(serializer.data)
        except DailyEmailStats.DoesNotExist:
            return Response(
                {'error': 'No statistics available yet'},
                status=404
            )
        
@csrf_exempt
@require_POST
def sns_endpoint(request):
    """
    Endpoint to receive SNS notifications from AWS SES
    """
    try:
        # Parse the JSON body
        message_data = json.loads(request.body.decode('utf-8'))
        
        # Handle SNS subscription confirmation
        if message_data.get('Type') == 'SubscriptionConfirmation':
            subscribe_url = message_data.get('SubscribeURL')
            logger.info(f"SNS Subscription confirmation received. URL: {subscribe_url}")
            
            # Automatically confirm the subscription
            import urllib.request
            urllib.request.urlopen(subscribe_url).read()
            logger.info("SNS Subscription confirmed successfully")
            
            return HttpResponse('Subscription confirmed', status=200)
        
        # Handle SNS notifications
        if message_data.get('Type') == 'Notification':
            # Parse the actual SES message from SNS
            ses_message = json.loads(message_data.get('Message', '{}'))
            
            # Determine event type - SES uses 'eventType' field
            event_type = ses_message.get('eventType', '').lower()
            
            # Map AWS event types to handlers
            if event_type == 'bounce':
                handle_bounce(ses_message)
            elif event_type == 'complaint':
                handle_complaint(ses_message)
            elif event_type == 'delivery':
                handle_delivery(ses_message)
            elif event_type == 'send':
                handle_send(ses_message)
            elif event_type == 'reject':
                handle_reject(ses_message)
            elif event_type == 'renderingfailure':
                handle_rendering_failure(ses_message)
            elif event_type == 'deliverydelay':
                handle_delivery_delay(ses_message)
            elif event_type == 'subscription':
                handle_subscription(ses_message)
            else:
                logger.warning(f"Unknown event type: {event_type}")
            
            return HttpResponse('OK', status=200)
        
        return HttpResponseBadRequest('Invalid message type')
        
    except Exception as e:
        logger.error(f"Error processing SNS notification: {str(e)}", exc_info=True)
        return HttpResponse('Error processing notification', status=500)


def handle_bounce(message):
    """Process bounce notifications"""
    from dateutil import parser as date_parser
    
    bounce = message.get('bounce', {})
    mail = message.get('mail', {})
    
    # Parse timestamp - it's in ISO format string
    timestamp_str = bounce.get('timestamp') or mail.get('timestamp')
    timestamp = date_parser.parse(timestamp_str) if timestamp_str else timezone.now()
    
    for recipient in bounce.get('bouncedRecipients', []):
        SESEvent.objects.create(
            event_type='bounce',
            message_id=mail.get('messageId', ''),
            email=recipient.get('emailAddress', ''),
            bounce_type=bounce.get('bounceType', ''),
            bounce_sub_type=bounce.get('bounceSubType', ''),
            timestamp=timestamp,
            raw_message=message
        )
        logger.info(f"Bounce recorded: {recipient.get('emailAddress')}")


def handle_complaint(message):
    """Process complaint notifications"""
    from dateutil import parser as date_parser
    
    complaint = message.get('complaint', {})
    mail = message.get('mail', {})
    
    # Parse timestamp - it's in ISO format string
    timestamp_str = complaint.get('timestamp') or mail.get('timestamp')
    timestamp = date_parser.parse(timestamp_str) if timestamp_str else timezone.now()
    
    for recipient in complaint.get('complainedRecipients', []):
        SESEvent.objects.create(
            event_type='complaint',
            message_id=mail.get('messageId', ''),
            email=recipient.get('emailAddress', ''),
            complaint_feedback_type=complaint.get('complaintFeedbackType', ''),
            timestamp=timestamp,
            raw_message=message
        )
        logger.info(f"Complaint recorded: {recipient.get('emailAddress')}")


def handle_delivery(message):
    """Process delivery notifications"""
    from dateutil import parser as date_parser
    
    delivery = message.get('delivery', {})
    mail = message.get('mail', {})
    
    # Parse timestamp - it's in ISO format string
    timestamp_str = delivery.get('timestamp') or mail.get('timestamp')
    timestamp = date_parser.parse(timestamp_str) if timestamp_str else timezone.now()
    
    for recipient in delivery.get('recipients', []):
        SESEvent.objects.create(
            event_type='delivery',
            message_id=mail.get('messageId', ''),
            email=recipient,
            timestamp=timestamp,
            raw_message=message
        )
        logger.info(f"Delivery recorded: {recipient}")


def handle_send(message):
    """Process send notifications"""
    from dateutil import parser as date_parser
    
    mail = message.get('mail', {})
    
    timestamp_str = mail.get('timestamp')
    timestamp = date_parser.parse(timestamp_str) if timestamp_str else timezone.now()
    
    for recipient in mail.get('destination', []):
        SESEvent.objects.create(
            event_type='send',
            message_id=mail.get('messageId', ''),
            email=recipient,
            timestamp=timestamp,
            raw_message=message
        )
        logger.info(f"Send recorded: {recipient}")


def handle_reject(message):
    """Process reject notifications"""
    from dateutil import parser as date_parser
    
    reject = message.get('reject', {})
    mail = message.get('mail', {})
    
    timestamp_str = mail.get('timestamp')
    timestamp = date_parser.parse(timestamp_str) if timestamp_str else timezone.now()
    
    for recipient in mail.get('destination', []):
        SESEvent.objects.create(
            event_type='reject',
            message_id=mail.get('messageId', ''),
            email=recipient,
            reject_reason=reject.get('reason', ''),
            timestamp=timestamp,
            raw_message=message
        )
        logger.info(f"Reject recorded: {recipient} - {reject.get('reason')}")


def handle_rendering_failure(message):
    """Process rendering failure notifications"""
    from dateutil import parser as date_parser
    
    failure = message.get('failure', {})
    mail = message.get('mail', {})
    
    timestamp_str = mail.get('timestamp')
    timestamp = date_parser.parse(timestamp_str) if timestamp_str else timezone.now()
    
    for recipient in mail.get('destination', []):
        SESEvent.objects.create(
            event_type='rendering_failure',
            message_id=mail.get('messageId', ''),
            email=recipient,
            reject_reason=failure.get('errorMessage', ''),
            timestamp=timestamp,
            raw_message=message
        )
        logger.info(f"Rendering failure recorded: {recipient}")


def handle_delivery_delay(message):
    """Process delivery delay notifications"""
    from dateutil import parser as date_parser
    
    delay = message.get('deliveryDelay', {})
    mail = message.get('mail', {})
    
    timestamp_str = delay.get('timestamp') or mail.get('timestamp')
    timestamp = date_parser.parse(timestamp_str) if timestamp_str else timezone.now()
    
    for recipient in delay.get('delayedRecipients', []):
        SESEvent.objects.create(
            event_type='delivery_delay',
            message_id=mail.get('messageId', ''),
            email=recipient.get('emailAddress', ''),
            timestamp=timestamp,
            raw_message=message
        )
        logger.info(f"Delivery delay recorded: {recipient.get('emailAddress')}")


def handle_subscription(message):
    """Process subscription notifications"""
    from dateutil import parser as date_parser
    
    subscription = message.get('subscription', {})
    mail = message.get('mail', {})
    
    timestamp_str = subscription.get('timestamp') or mail.get('timestamp')
    timestamp = date_parser.parse(timestamp_str) if timestamp_str else timezone.now()
    
    for contact in subscription.get('contactList', {}).get('contacts', []):
        SESEvent.objects.create(
            event_type='subscription',
            message_id=mail.get('messageId', ''),
            email=contact.get('emailAddress', ''),
            timestamp=timestamp,
            raw_message=message
        )
        logger.info(f"Subscription recorded: {contact.get('emailAddress')}")

from django.utils.safestring import mark_safe
from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.views.decorators.clickjacking import xframe_options_exempt

from cis.menu import draw_menu, cis_menu
from django.urls import reverse


class BouncesComplaintsListView(View):
    """
    View for displaying bounces and complaints
    """
    def get(self, request, *args, **kwargs):
        menu = draw_menu(cis_menu, 'ses_daily_stats', 'ses_bounces_complaints')
        return render(request, 'ses_tracking/bounces_complaints/list.html', {
            'menu': menu,
            'page_title': 'Bounces & Complaints',
            'api_url': '/ses/webhooks/api/events/',
        })

class DailyEmailStatsListView(View):

    def get(self, request, *args, **kwargs):

        menu = draw_menu(cis_menu, 'ses_daily_stats', 'ses_daily_stats')
        return render(request, 'ses_tracking/daily_stats/list.html', {
            'menu': menu,
            'page_title': 'Daily Email Stats',
            'api_url': reverse('ses_tracking:daily-stats-list'),  # Best practice
        })