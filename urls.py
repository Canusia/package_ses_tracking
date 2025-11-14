from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views as api_views
from . import views as webhook_views


app_name = 'ses_tracking'

# API Router
router = DefaultRouter()
router.register(r'stats', api_views.DailyEmailStatsViewSet, basename='daily-stats')
router.register(r'events', api_views.SESEventViewSet, basename='ses-events')

urlpatterns = [
    # Webhook endpoint (existing)
    path('sns/ses-events/', webhook_views.sns_endpoint, name='sns_endpoint'),
    
    # API endpoints
    path('api/', include(router.urls)),

    path('sns/bounces-complaints/', webhook_views.BouncesComplaintsListView.as_view(), name='bounces-complaints'),
    
    path('sns/daily_email_stats/', webhook_views.DailyEmailStatsListView.as_view(), name='daily-email-stats')
]