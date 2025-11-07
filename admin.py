
# ses_tracking/admin.py
from django.contrib import admin
from .models import SESEvent


@admin.register(SESEvent)
class SESEventAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'event_type', 'email', 'bounce_type', 'reject_reason', 'message_id']
    list_filter = ['event_type', 'bounce_type', 'timestamp']
    search_fields = ['email', 'message_id', 'reject_reason']
    readonly_fields = ['event_type', 'message_id', 'email', 'bounce_type', 
                      'bounce_sub_type', 'complaint_feedback_type', 'reject_reason',
                      'timestamp', 'raw_message', 'created_at']
    date_hierarchy = 'timestamp'
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
