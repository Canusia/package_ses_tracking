# Django SES Tracking

A Django app for tracking AWS SES email events including bounces, complaints, deliveries, sends, rejects, rendering failures, and delivery delays.

## Features

- 📧 Tracks all AWS SES email events
- 🔔 Automatic SNS webhook subscription confirmation
- 📊 Django admin interface for viewing events
- 📈 Daily statistics aggregation with management command
- 🔌 Custom email backend with automatic configuration set injection
- 🚀 Works seamlessly with django-mailer
- 🎯 Separate tracking per app/environment
- 🌐 RESTful API with DataTables integration
- 📱 Responsive web interface for viewing stats, bounces, and complaints

## Installation

### Via pip from GitHub (Production)
```bash
pip install git+https://github.com/Canusia/package_ses_tracking.git@v1.0.0
```

Or add to your `requirements.txt`:
git+https://github.com/Canusia/package_ses_tracking.git@v2.0.5

### Via Git Submodule (Development)
```bash
# In your Django project root
git submodule add https://github.com/Canusia/package_ses_tracking.git
git submodule update --init --recursive
```

Then add to your Python path or install in editable mode:
```bash
pip install -e ./package_ses_tracking
```

## Quick Start

### 1. Add to INSTALLED_APPS
```python
# settings.py
INSTALLED_APPS = [
    # ... other apps
    'rest_framework',  # Required for API views
    'ses_tracking',
]
```

### 2. Configure Email Backend
```python
# settings.py
EMAIL_BACKEND = 'mailer.backend.DbBackend'  # django-mailer
MAILER_EMAIL_BACKEND = 'ses_tracking.backend.SESBackend'  # SES tracking backend

# Your existing SMTP settings
EMAIL_HOST = 'email-smtp.us-east-1.amazonaws.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'your-smtp-username'
EMAIL_HOST_PASSWORD = 'your-smtp-password'

# SES Configuration
AWS_SES_REGION = 'us-east-1'
AWS_SES_CONFIGURATION_SET = 'your-config-set-name'

# Optional: DRF Configuration
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 25,
}
```

### 3. Add URL Patterns
```python

# add to myce/urls.py
from django.urls import path, include

urlpatterns += [
    path('ses/webhooks/', include('ses_tracking.urls')),
]

# in settings.py
INSTALLED_APPS += [
    'ses_tracking',
]

STATICFILES_DIRS += [
    os.path.join(get_package_path("ses_tracking"), 'staticfiles') if get_package_path("ses_tracking") else None
]

# Tell django-mailer to use your custom backend
MAILER_EMAIL_BACKEND = 'ses_tracking.backend.SESBackend'

# Add SES configuration
AWS_SES_REGION = 'us-east-1'
AWS_SES_CONFIGURATION_SET = '<match>-config-set'
```

### 4. Run Migrations
```bash
python manage.py migrate ses_tracking

# add to cron_jobs.py
try:
    call_command(
        "aggregate_daily_stats",
        date=datetime.date.today().isoformat(),
        force=True
    )
except Exception as e:
    logger.error(f"Error aggregating daily stats: {e}")

# add menu to settings
{
    "type":"nav-item",
    "icon":"fas fa-fw fa-envelope",
        "name":"ses_daily_stats",
    "label":"Email Stats",
    "sub_menu":[
        {
        "label":"Daily Email Stats",
        "name":"ses_daily_stats",
        "url":"ses_tracking:daily-email-stats"
        },
        {
        "label":"Bounces/Complaints",
        "name":"ses_bounces_complaints",
        "url":"ses_tracking:bounces-complaints"
        }
    ]
},
```

### 5. Set Up AWS Infrastructure

Use the included AWS CDK stack to set up SNS topics and SES configuration (see `docs/aws-setup.md`).

Your webhook URL will be: `https://yourdomain.com/webhooks/sns/ses-events/`

## Usage

### Sending Emails

Once configured, all emails sent through your Django app will automatically:
- Include the SES configuration set header
- Trigger SNS notifications for events
- Store events in the database
- Be viewable in Django admin at `/admin/ses_tracking/sesevent/`

No code changes needed! Just send emails as usual:
```python
from mailer import send_html_mail
from django.conf import settings

send_html_mail(
    'Subject',
    'Plain text body',
    '<h1>HTML body</h1>',
    settings.DEFAULT_FROM_EMAIL,
    ['recipient@example.com']
)
```

### Daily Statistics Aggregation

Aggregate email events into daily statistics:
```bash
# Process yesterday's data (run daily via cron)
python manage.py aggregate_daily_stats

# Process specific date
python manage.py aggregate_daily_stats --date 2025-11-07

# Process multiple days
python manage.py aggregate_daily_stats --days 7

# Force regeneration
python manage.py aggregate_daily_stats --force
```

**Set up cron job** (run at 1 AM daily):
```bash
0 1 * * * /path/to/venv/bin/python /path/to/project/manage.py aggregate_daily_stats
```

### Web Interface Views

The package includes two ready-to-use views with DataTables integration:

#### 1. Daily Statistics View
```python
# your_app/views.py
from django.views import View
from django.shortcuts import render

class DailyEmailStatsListView(View):
    def get(self, request, *args, **kwargs):
        return render(request, 'ses_tracking/daily_stats/list.html', {
            'page_title': 'Daily Email Stats',
            'api_url': '/webhooks/api/stats/',
        })

# urls.py
urlpatterns = [
    path('email-stats/', DailyEmailStatsListView.as_view(), name='email-stats'),
]
```

Access at: `https://yourdomain.com/email-stats/`

**Features:**
- View daily aggregated statistics
- Date range filtering
- Sortable columns
- Color-coded bounce/complaint/delivery rates
- Server-side pagination

#### 2. Bounces & Complaints View
```python
# your_app/views.py
class BouncesComplaintsListView(View):
    def get(self, request, *args, **kwargs):
        return render(request, 'ses_tracking/bounces_complaints/list.html', {
            'page_title': 'Bounces & Complaints',
            'api_url': '/webhooks/api/events/',
        })

# urls.py
urlpatterns = [
    path('bounces-complaints/', BouncesComplaintsListView.as_view(), name='bounces-complaints'),
]
```

Access at: `https://yourdomain.com/bounces-complaints/`

**Features:**
- Three tabs: All Events, Bounces Only, Complaints Only
- View email subject, to address, timestamp
- Independent date filters per tab
- Color-coded status indicators
- Searchable and sortable

### REST API Endpoints

The package provides a full RESTful API:

#### Daily Statistics API
```bash
# List all stats (paginated)
GET /webhooks/api/stats/

# Get specific day
GET /webhooks/api/stats/{id}/

# Get recent summary
GET /webhooks/api/stats/summary/?days=7

# Get date range
GET /webhooks/api/stats/date_range/?start_date=2025-11-01&end_date=2025-11-07

# Get aggregated totals
GET /webhooks/api/stats/aggregate/?start_date=2025-11-01&end_date=2025-11-07

# Get latest stats
GET /webhooks/api/stats/latest/
```

#### Events API (Bounces & Complaints)
```bash
# List all bounces and complaints
GET /webhooks/api/events/

# Filter by event type
GET /webhooks/api/events/?event_type=bounce
GET /webhooks/api/events/?event_type=complaint

# Filter by date range
GET /webhooks/api/events/?start_date=2025-11-01&end_date=2025-11-07

# Search
GET /webhooks/api/events/?search=user@example.com
```

## Event Types Tracked

- **Bounce**: Hard bounces and soft bounces after retry exhaustion
- **Complaint**: Spam complaints from recipients
- **Delivery**: Successful email deliveries
- **Send**: Email accepted by SES
- **Reject**: Email rejected due to virus or policy
- **Rendering Failure**: Template rendering failures
- **Delivery Delay**: Temporary delivery issues
- **Subscription**: Unsubscribe actions

## Configuration Options

| Setting | Description | Default |
|---------|-------------|---------|
| `AWS_SES_REGION` | AWS region for SES | `us-east-1` |
| `AWS_SES_CONFIGURATION_SET` | SES configuration set name | `default-config-set` |

## Admin Interface

Access the admin at:
- `/admin/ses_tracking/sesevent/` - Individual email events
- `/admin/ses_tracking/dailyemailstats/` - Daily aggregated statistics

Features:
- View all tracked events
- Filter by event type, bounce type, timestamp
- Search by email address, subject, message ID
- View full raw SNS message for debugging
- Date hierarchy navigation

## AWS Setup

See `docs/aws-setup.md` for complete AWS CDK setup instructions including:
- SNS topic creation
- SES configuration set setup
- Event destination configuration
- Webhook subscription

## Management Commands

### aggregate_daily_stats

Aggregate SES events into daily statistics.

**Options:**
- `--date YYYY-MM-DD`: Specific date to process (defaults to yesterday)
- `--days N`: Number of days to process backwards (default: 1)
- `--force`: Force regeneration even if stats exist

**Examples:**
```bash
# Daily cron job
python manage.py aggregate_daily_stats

# Backfill last 30 days
python manage.py aggregate_daily_stats --days 30

# Regenerate specific date
python manage.py aggregate_daily_stats --date 2025-11-07 --force
```

## Requirements

- Python 3.8+
- Django 3.2+
- djangorestframework 3.12+
- boto3
- python-dateutil
- django-mailer

## License

MIT License - see LICENSE file for details.

## Support

For issues, questions, or contributions, please open an issue on GitHub: https://github.com/Canusia/package_ses_tracking/issues

## Changelog

### v1.0.0
- Initial release
- AWS SES event tracking
- Daily statistics aggregation
- RESTful API with DataTables support
- Web interface views
- Django admin integration
- AWS CDK infrastructure templates