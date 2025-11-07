from django.urls import path
from . import views

app_name = 'ses_tracking'

urlpatterns = [
    path('sns/ses-events/', views.sns_endpoint, name='sns_endpoint'),
]