# ses_tracking/serializers.py
from rest_framework import serializers
from .models import DailyEmailStats, SESEvent


class DailyEmailStatsSerializer(serializers.ModelSerializer):
    """
    Serializer for DailyEmailStats model
    """
    bounce_rate_display = serializers.SerializerMethodField()
    complaint_rate_display = serializers.SerializerMethodField()
    delivery_rate_display = serializers.SerializerMethodField()
    
    class Meta:
        model = DailyEmailStats
        fields = [
            'id',
            'date',
            'total_sends',
            'total_deliveries',
            'total_bounces',
            'total_complaints',
            'total_rejects',
            'total_rendering_failures',
            'total_delivery_delays',
            'total_subscriptions',
            'permanent_bounces',
            'transient_bounces',
            'undetermined_bounces',
            'bounce_rate',
            'bounce_rate_display',
            'complaint_rate',
            'complaint_rate_display',
            'delivery_rate',
            'delivery_rate_display',
            'unique_recipients',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields  # All fields are read-only
    
    def get_bounce_rate_display(self, obj):
        return f"{obj.bounce_rate}%"
    
    def get_complaint_rate_display(self, obj):
        return f"{obj.complaint_rate}%"
    
    def get_delivery_rate_display(self, obj):
        return f"{obj.delivery_rate}%"


class DailyEmailStatsSummarySerializer(serializers.ModelSerializer):
    """
    Lightweight serializer with just key metrics
    """
    bounce_rate_display = serializers.SerializerMethodField()
    complaint_rate_display = serializers.SerializerMethodField()
    delivery_rate_display = serializers.SerializerMethodField()
    
    class Meta:
        model = DailyEmailStats
        fields = [
            'date',
            'total_sends',
            'total_deliveries',
            'total_bounces',
            'total_complaints',
            'bounce_rate',
            'bounce_rate_display',
            'complaint_rate',
            'complaint_rate_display',
            'delivery_rate',
            'delivery_rate_display',
        ]
    
    def get_bounce_rate_display(self, obj):
        return f"{obj.bounce_rate}%"
    
    def get_complaint_rate_display(self, obj):
        return f"{obj.complaint_rate}%"
    
    def get_delivery_rate_display(self, obj):
        return f"{obj.delivery_rate}%"

class SESEventSerializer(serializers.ModelSerializer):
    """
    Serializer for SES Events (bounces and complaints)
    """
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)
    bounce_type_display = serializers.CharField(source='get_bounce_type_display', read_only=True)
    
    class Meta:
        model = SESEvent
        fields = [
            'id',
            'event_type',
            'event_type_display',
            'timestamp',
            'email',
            'email_to',
            'email_subject',
            'email_message_id',
            'bounce_type',
            'bounce_type_display',
            'bounce_sub_type',
            'complaint_feedback_type',
            'reject_reason',
            'message_id',
        ]
        read_only_fields = fields