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

## Role-Based Email Routing (`routing.py`)

A `RoutingBackend` / `RoutingSESBackend` pair (also in `backend.py`) rewrites
recipients per role at delivery time, before delegating to the inner
backend. In this deployment:
```python
EMAIL_BACKEND = 'ses_tracking.backend.RoutingBackend'
MAILER_EMAIL_BACKEND = 'ses_tracking.backend.RoutingSESBackend'
```

Do not collapse these two settings to the same value, and do not point
`MAILER_EMAIL_BACKEND` at the plain `RoutingBackend` -- only
`RoutingSESBackend` guarantees its inner backend is `SESBackend`.
`RoutingBackend` alone would fall through to a generic SMTP inner backend and
silently drop the `X-SES-CONFIGURATION-SET` header, zeroing out bounce and
complaint tracking with no error anywhere.

### Configuration

Governed by the `Email Routing by Role` setting (CE Admin > Settings),
stored under the setting key `ses_tracking.settings.email_routing` as:
```python
{'mode': 'active' | 'inactive', 'roles': {'<role-slug>': ['primary', 'secondary', 'alt'], ...}}
```
`mode` is the kill switch; `roles` maps each MyCE role slug to the list of
address kinds (`primary` = `email`, `secondary` = `secondary_email`, `alt` =
`alt_email`) mail addressed to that role's users should be delivered to.

**Ships inactive.** `install()` seeds every role at `['primary']` but leaves
`mode: 'inactive'` -- seeding `'active'` would not be inert, because the
resolution below covers every address a matched user owns, not just the one
a message was addressed to. A CE admin must deliberately switch it on.

### Resolution semantics (`ses_tracking/routing.py`)

1. **Drop-if-not-selected** -- an address kind not selected for a role is not
   delivered to; that is the only way to stop mail reaching an unread
   mailbox. An empty selection for a role means "not configured," not
   "suppress" -- routing leaves that role's mail at the original address
   (today's behavior), it does not drop it.
2. **Union across roles** -- a user's delivery set is the union of the kinds
   selected for every group they belong to.
3. **Primary preferred, then first match** -- `email` is unique, but
   `secondary_email`/`alt_email` are not, so an incoming address can match
   several users (e.g. a shared high-school office mailbox). The user whose
   *primary* address matches wins over any user who only matches via
   secondary/alt; ties within either class break by ascending `pk`.
4. **Fallback to original** -- if the selected kinds resolve to no valid
   address for a matched user, that user's mail is left untouched instead of
   being dropped.

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
