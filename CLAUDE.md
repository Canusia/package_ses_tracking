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
- `open` - Opened (SES open tracking; needs Open on the configuration set)

## URL Structure
```
/ses/webhooks/sns/ses-events/  # SNS webhook endpoint
```

## Security (#2)

- `sns_endpoint` is public (csrf-exempt, `login_required = False`), so it trusts
  nothing until `sns_verify.verify()` passes: signature checked against the SNS
  signing cert (fetched only from `https://sns.<region>.amazonaws.com`, cached
  per process), SignatureVersion 1/2, optional `SES_TRACKING_ALLOWED_TOPIC_ARNS`
  allow-list (unset = any signed topic, with a warning). Failures are 403 and
  store nothing; `SubscribeURL` is followed only if it is also on sns.*.amazonaws.com.
- `SESEventViewSet` / `DailyEmailStatsViewSet` use `CIS_user_only`; the two page
  views are wrapped in `user_passes_test(user_has_cis_role)`. Never rely on the
  tenant's DRF default (it is only `IsAuthenticated`).
- Version lives in BOTH `setup.py` (`version=`, which wins) and `setup.cfg`;
  bump both to the tag being cut.

## Email Backend (`backend.py`)

Custom SMTP backend that injects SES configuration set header:
```python
EMAIL_BACKEND = 'mailer.backend.DbBackend'  # django-mailer
MAILER_EMAIL_BACKEND = 'ses_tracking.backend.SESBackend'
```

Adds the `X-SES-CONFIGURATION-SET` header to outgoing email when a set is configured.
There is **no fallback** (#3): the old `'rmu-config-set'` default tagged other tenants' mail
into RMU's set. Unset means no header.

**Per-campus (#3, `campus_mail.py`):** `SES_CAMPUS_CONFIG` maps a campus code to a
`from_email` / `configuration_set`. Mail is stamped with `X-MyCE-Campus` at creation, by
`RoutingBackend.apply_campus` and by the `mailer.Message` `pre_save` connected in
`apps.ready()`. `SESBackend._send` resolves it (`campus_mail.resolve`), and the header is
always stripped before SMTP. The default sender is swapped only when it equals
`DEFAULT_FROM_EMAIL`. Everything is a no-op when `SES_CAMPUS_CONFIG` is empty: keep it
that way, since about 50 single-campus tenants must not pay a campus lookup per send.
`SESEvent.campus_code` is filled in `save()` from `mail.tags['ses:configuration-set']`.

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
