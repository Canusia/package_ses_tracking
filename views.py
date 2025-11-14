
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

logger = logging.getLogger(__name__)

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
sns_endpoint.login_required = False

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
