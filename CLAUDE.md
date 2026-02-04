# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Tracks AWS SES email events via SNS webhooks. Stores delivery, bounce, complaint, and other events. Provides daily statistics aggregation and Django admin for inspection.

## Key Components

### Models (`models.py`)
- **SESEvent** - Individual email events with type, message_id, email, bounce/complaint details, raw SNS message
- **DailyEmailStats** - Aggregated daily statistics with counts and rates

### Event Types
- `send` - Email accepted by SES
- `delivery` - Successful delivery
- `bounce` - Hard/soft bounce (with type and subtype)
- `complaint` - Spam complaint
- `reject` - Policy/virus rejection
- `rendering_failure` - Template error
- `delivery_delay` - Temporary delay
- `subscription` - Unsubscribe action

## URL Structure
```
/ses/webhooks/sns/ses-events/  # SNS webhook endpoint
```

## Email Backend (`backend.py`)

Custom SMTP backend that injects SES configuration set header:
```python
EMAIL_BACKEND = 'mailer.backend.DbBackend'  # django-mailer
MAILER_EMAIL_BACKEND = 'ses_tracking.backend.SESBackend'
```

Automatically adds `X-SES-CONFIGURATION-SET` header to all outgoing emails.

## Commands

```bash
python manage.py aggregate_daily_stats              # Aggregate yesterday's stats
python manage.py aggregate_daily_stats --date 2024-01-15  # Specific date
python manage.py aggregate_daily_stats --days 7    # Last 7 days
python manage.py aggregate_daily_stats --force     # Regenerate existing
```

## Configuration

```python
# settings.py
AWS_SES_REGION = 'us-east-1'
AWS_SES_CONFIGURATION_SET = 'your-config-set-name'
OVERRIDE_BOUNCE_RATE = False  # Set True to disable bounce rate validation
```

## AWS Setup

1. Create SES Configuration Set in AWS Console
2. Add SNS destination for all event types
3. Create SNS topic subscription pointing to webhook URL
4. App automatically confirms SNS subscription

## Webhook Flow

1. AWS SES publishes event to SNS topic
2. SNS POSTs to `/ses/webhooks/sns/ses-events/`
3. `sns_endpoint` view:
   - Confirms subscription requests automatically
   - Routes to event-specific handlers
   - Creates SESEvent records
4. Daily cron aggregates into DailyEmailStats

## Admin Interface

- `/admin/ses_tracking/sesevent/` - Read-only event inspection
- `/admin/ses_tracking/dailyemailstats/` - Daily metrics view

## Integration

- Works with `django-mailer` for async email queue
- Stores raw SNS messages for debugging
- `DailyEmailStats.is_bounce_rate_acceptable()` for health checks
