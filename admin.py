# ses_tracking/admin.py
from django.contrib import admin
from .models import SESEvent, DailyEmailStats


@admin.register(SESEvent)
class SESEventAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'event_type', 'email', 'email_message_id', 'bounce_type', 'reject_reason', 'message_id']
    list_filter = ['event_type', 'bounce_type', 'timestamp']
    search_fields = ['email', 'message_id', 'email_message_id', 'reject_reason']
    readonly_fields = ['event_type', 'message_id', 'email_message_id', 'email', 'bounce_type', 
                      'bounce_sub_type', 'complaint_feedback_type', 'reject_reason',
                      'timestamp', 'raw_message', 'created_at']
    date_hierarchy = 'timestamp'
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(DailyEmailStats)
class DailyEmailStatsAdmin(admin.ModelAdmin):
    list_display = [
        'date', 
        'total_sends', 
        'total_deliveries', 
        'total_bounces', 
        'total_complaints', 
        'bounce_rate_display',
        'complaint_rate_display', 
        'delivery_rate_display',
        'unique_recipients'
    ]
    list_filter = ['date']
    readonly_fields = [
        'date', 'total_sends', 'total_deliveries', 'total_bounces', 
        'total_complaints', 'total_rejects', 'total_rendering_failures',
        'total_delivery_delays', 'total_subscriptions', 'permanent_bounces',
        'transient_bounces', 'undetermined_bounces', 'bounce_rate', 
        'complaint_rate', 'delivery_rate', 'unique_recipients',
        'created_at', 'updated_at'
    ]
    date_hierarchy = 'date'
    ordering = ['-date']
    
    def bounce_rate_display(self, obj):
        return f"{obj.bounce_rate}%"
    bounce_rate_display.short_description = 'Bounce Rate'
    
    def complaint_rate_display(self, obj):
        return f"{obj.complaint_rate}%"
    complaint_rate_display.short_description = 'Complaint Rate'
    
    def delivery_rate_display(self, obj):
        return f"{obj.delivery_rate}%"
    delivery_rate_display.short_description = 'Delivery Rate'
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        # Allow deletion to regenerate stats if needed
        return True