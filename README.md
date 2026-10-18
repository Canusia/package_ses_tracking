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

OVERRIDE_BOUNCE_RATE = False
```

### 2.1 (Optional) Role-Based Email Routing

To rewrite recipients per role at delivery time -- e.g. sending mail to a
user's `secondary_email` instead of their `email` for certain roles -- wire
the routing backends instead of `SESBackend` directly:
```python
EMAIL_BACKEND = 'ses_tracking.backend.RoutingBackend'
MAILER_EMAIL_BACKEND = 'ses_tracking.backend.RoutingSESBackend'
```
Use `RoutingSESBackend`, not the plain `RoutingBackend`, for
`MAILER_EMAIL_BACKEND`: only `RoutingSESBackend` guarantees `SESBackend` as
its inner backend. Using the plain `RoutingBackend` there would silently
drop the `X-SES-CONFIGURATION-SET` header and zero out bounce/complaint
tracking.

Routing is governed by the `Email Routing by Role` setting, stored as:
```python
{'mode': 'active' | 'inactive', 'roles': {'<role-slug>': ['primary', 'secondary', 'alt'], ...}}
```
It **ships inactive** -- `install()` seeds every role's kinds but leaves
`mode` off, since seeding `'active'` would not be a no-op (it would rewrite
every address a matched user owns, not just the incoming one). A CE admin
must deliberately switch it on. Resolution semantics: an unselected kind is
dropped from delivery (but an *entirely empty* selection for a role means
"not configured" and leaves that role's mail unchanged, not suppressed); a
user's kinds are the union across all their roles; when several users share
a non-primary address, the user whose *primary* matches wins, else the
lowest-`pk` match; and if nothing valid resolves, the original address is
left alone. See `ses_tracking/routing.py` and `CLAUDE.md` for details.

### 3. Add URL Patterns
```python
# urls.py
from django.urls import path, include

urlpatterns = [
    # ... other patterns
    path('webhooks/', include('ses_tracking.urls')),
]
```

### 3.1 Add to cronjob.py
```python
# cronjob.py
try:
    call_command(
        "aggregate_daily_stats",
        date=datetime.date.today().isoformat(),
        force=True
    )
except Exception as e:
    logger.error(f"Error aggregating daily stats: {e}")
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
| `AWS_SES_CONFIGURATION_SET` | SES configuration set name. **No implicit fallback (since v4.4.0):** when unset or `None`, mail is sent without the `X-SES-CONFIGURATION-SET` header and is not tracked. | unset |
| `SES_CAMPUS_CONFIG` | Multi-campus only: `{'<campus code>': {'from_email': ..., 'configuration_set': ...}}`. See *Per-campus sender* below. | unset |
| `SES_TRACKING_ALLOWED_TOPIC_ARNS` | SNS topic ARNs the webhook accepts. Recommended; when unset, any correctly signed topic is accepted and a warning is logged. | unset |

## Per-campus sender and configuration set (multi-campus)

```python
SES_CAMPUS_CONFIG = {
    'LAMAR_A': {'from_email': 'noreply@lit.edu', 'configuration_set': 'lamar-lit'},
    'LAMAR_B': {'from_email': 'noreply@lamarpa.edu', 'configuration_set': 'lamar-lscpa'},
}
```

- **Stamped at creation, resolved at delivery.** Mail created inside a campus context (a
  request on that campus's host, or a `run_for_each_campus` job) gets an internal
  `X-MyCE-Campus` header. Direct sends are stamped by `RoutingBackend`. Queued sends are
  stamped by a `pre_save` on `mailer.models.Message` (`send_mail` / `send_html_mail`).
  `SESBackend` resolves the stamp at flush time and strips it before SMTP.
- **Sender:** replaced with the campus `from_email` only when it is `DEFAULT_FROM_EMAIL`
  (compared by address; any display name is kept). Explicit senders are kept. Every
  `from_email` must be a verified SES identity.
- **Configuration set:** the campus's set, else `AWS_SES_CONFIGURATION_SET`, else no header.
- **Events:** `SESEvent.campus_code` is filled from the event's configuration set, and the
  events API accepts `?campus=<code>`.
- Unset or empty `SES_CAMPUS_CONFIG` means nothing is stamped and no campus is looked up, so
  single-campus tenants are unchanged.
- Limit: django-mailer's own `DbBackend` enqueues with `bulk_create` (no signals). Mail that
  reaches it through `RoutingBackend` is already stamped; a deployment wiring `DbBackend`
  directly as `EMAIL_BACKEND` gets queue stamping only for `send_mail` / `send_html_mail`.

## Security

- **The webhook only trusts genuine SNS messages.** Every message's signature
  is verified against the SNS signing certificate, which is only fetched from
  `https://sns.<region>.amazonaws.com`. `SignatureVersion` 1 (SHA1) and 2
  (SHA256) are supported. Unsigned or tampered messages get `403` and store
  nothing. Subscriptions are auto-confirmed only for a signed message whose
  `SubscribeURL` is on `https://sns.<region>.amazonaws.com`.
- **The API (`api/events/`, `api/stats/` and its actions) and both pages are CE
  staff only** (`cis.utils.CIS_user_only` / `user_has_cis_role`). They expose
  recipient addresses, subjects and tenant-wide email metrics.

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
- cryptography (SNS signature verification)

## License

MIT License - see LICENSE file for details.

## Support

For issues, questions, or contributions, please open an issue on GitHub: https://github.com/Canusia/package_ses_tracking/issues
## Sent Email log (v4.5.0)

Every message that leaves through `RoutingBackend` / `RoutingSESBackend` is recorded as a
`SentEmail` (`capture.py`), after role routing and debug routing and just before the inner
send. The row's UUID goes to SES as the message tag `myce-id` (`X-SES-MESSAGE-TAGS`, merged
with any existing tags), and SES copies tags onto every event, so `events.link()` joins each
`SESEvent` to its row: delivery / bounce / complaint / reject / delay move `status` forward
only, and `open` events set `first_opened_at` and `open_count`. Recording never costs a
message: a capture error is logged and the mail goes out untagged.

- **Permission:** `ses_tracking.view_sent_email` ("Can view sent email"), denied by default;
  superusers pass. Page, tab and API all require a CIS role **and** the permission
  (`permissions.can_view_sent_email`). The CE menu item (under Email Stats, seeded by
  migration 0008) is visible to all CE staff -- `draw_menu` has no permission hook -- and
  shows a 403 page naming the permission to users without it.
- **Page:** `/ses/webhooks/sent-email/` (`ses_tracking:sent-email`). **API:**
  `/ses/webhooks/api/sent-email/` -- the list serializer never includes bodies; filters
  `address`, `person` (exact addresses, comma-separated), `status`, `opened` (yes/no/na),
  `path`, `campus`, `start_date`, `end_date`. HTML bodies render only in a sandboxed
  `srcdoc` iframe.
- **Emails tab:** registered from `apps.ready()` (`tabs.py`) on the student, teacher and
  hs_administrator registries in the tenant's `myce/component_registry`, when present.
- **Opens are approximate** and need an HTML part (`SentEmail.trackable`).
- **Stored bodies never hold live credentials.** Anyone with `view_sent_email` can read
  them, so Django password-reset links (`password_reset/<uidb64>/<token>/`) are replaced
  with `[link removed]` in the stored copy (the recipient still gets the real link). Add
  patterns with `SES_TRACKING_BODY_REDACT_PATTERNS`. A sender can keep a message's bodies
  out of the log entirely with the header `X-MyCE-No-Body-Log: 1` (stripped before
  sending) -- use it for one-time codes.
- **Recording never touches the caller's transaction:** each row is written in a savepoint
  (django-mailer sends inside `atomic()`; an aborted transaction there would re-queue mail
  already sent). Per-person lookups use `SentEmailRecipient` (indexed exact address).
- If a tenant's `SES_TRACKING_ROUTING_INNER_BACKEND` is django-mailer's `DbBackend`, the
  enqueue step neither records nor debug-routes; the queue flush does both once.
- **Retention:** setting `sent_email` (`body_retention_days` 180, `log_retention_days` 730);
  `manage.py prune_sent_email [--dry-run]`, scheduled daily through the cis `CronTab`
  (seeded by migration 0007).
- **Direct sends** (`path='direct'`) get no SES events until they go through django-mailer
  (package-cis#101).

### AWS setup for opens

In SES, on the tenant's configuration set, edit the existing SNS event destination and add
**Open** to its event types. Leave **Click** off: it rewrites every link (password-reset and
parent-consent links included) through an AWS redirect. Nothing else changes -- same topic,
same webhook.

## Staging debug routing (v4.5.0)

`debug_routing.py`. Switched **only** by `settings.SES_TRACKING_DEBUG_ROUTING`, which a tenant
sets from the environment:

```python
SES_TRACKING_DEBUG_ROUTING = os.getenv('EMAIL_DEBUG_ROUTING') == 'True'
```

with `EMAIL_DEBUG_ROUTING=True` only in its staging and pull-request manifests. Never switch
it from the database: databases are copied between production and staging.

While on, every to/cc/bcc recipient is replaced: a user goes to the debug lists of their
roles (union), anyone else -- non-users, roles without a list -- to the "everyone else" list.
Lists are fields on the **Email Routing by Role** setting (`debug_lists`,
`debug_everyone_else`). **Fails closed:** an empty result drops that recipient (WARNING log);
a message left with nobody is not sent; an unsaved setting drops all mail. Redirected mail
gets the subject prefix `[STAGING → <first original address>]` and `X-MyCE-Original-To`, and
`SentEmail.debug_routed=True`. Set the lists on staging **before** deploying with the switch on.
