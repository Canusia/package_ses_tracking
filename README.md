# Django SES Tracking

A Django app for tracking AWS SES email events including bounces, complaints, deliveries, sends, rejects, rendering failures, and delivery delays.

## Features

- 📧 Tracks all AWS SES email events
- 🔔 Automatic SNS webhook subscription confirmation
- 📊 Django admin interface for viewing events
- 🔌 Custom email backend with automatic configuration set injection
- 🚀 Works seamlessly with django-mailer
- 🎯 Separate tracking per app/environment

## Installation

### Via pip from GitHub (Production)
```bash
pip install git+https://github.com/Canusia/package_ses_tracking.git@v1.0.0
```

Or add to your `requirements.txt`:

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
```

### 3. Add URL Patterns
```python
# urls.py
from django.urls import path, include

urlpatterns = [
    # ... other patterns
    path('webhooks/', include('ses_tracking.urls')),
]
```

### 4. Run Migrations
```bash
python manage.py migrate ses_tracking
```

### 5. Set Up AWS Infrastructure

Use the included AWS CDK stack to set up SNS topics and SES configuration (see `docs/aws-setup.md`).

Your webhook URL will be: `https://yourdomain.com/webhooks/sns/ses-events/`

## Usage

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

Access the admin at `/admin/ses_tracking/sesevent/` to:
- View all tracked events
- Filter by event type, bounce type, timestamp
- Search by email address or message ID
- View full raw SNS message for debugging

## AWS Setup

See `docs/aws-setup.md` for complete AWS CDK setup instructions.

## Requirements

- Python 3.8+
- Django 3.2+
- boto3
- python-dateutil
- django-mailer

## License

MIT License - see LICENSE file for details.

## Support

For issues, questions, or contributions, please open an issue on GitHub: https://github.com/Canusia/package_ses_tracking/issues