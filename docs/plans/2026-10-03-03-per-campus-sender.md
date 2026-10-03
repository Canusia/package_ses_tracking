# #3 — Per-campus default sender and SES configuration set

> Implemented inline (native execution). Written against `v4.3.0` / `8f3e222`.

**Goal:** In a multi-campus deployment each campus sends **from its own default sender** and
**through its own SES configuration set**, for direct and queued mail. Single-campus tenants
see no change. The implicit `'rmu-config-set'` fallback is removed.

**Architecture:** New module `campus_mail.py` with three steps.
1. **Stamp:** when mail is created inside a campus context, add the `X-MyCE-Campus: <code>` header.
2. **Resolve:** at delivery, read the header and swap the sender (only when it is the deployment
   default) and pick the configuration set.
3. **Strip:** remove the header before SMTP.

Stamping happens in two places: `RoutingBackend.send_messages` for direct sends, and a `pre_save`
on `mailer.models.Message` for queued sends, because enqueue runs in the campus context and the
flush does not. Resolution happens in `SESBackend._send`. When `RoutingBackend`'s inner backend
is neither SES nor the mailer queue, it resolves the sender and strips the header itself, so the
internal header never reaches a plain SMTP payload.

## Global Constraints

- **Zero cost when unconfigured:** with `SES_CAMPUS_CONFIG` unset or empty, nothing is stamped
  and the campus is not looked up. Single-campus tenants get no extra query per send.
- `cis` is imported softly: no `cis` means no campus, which means today's behaviour.
- The sender is replaced only when its address equals `DEFAULT_FROM_EMAIL`'s address (any display
  name is kept). Explicit senders are kept as they are.
- The configuration set comes from the campus, else `AWS_SES_CONFIGURATION_SET`, else **no header**.
- Version lives in `setup.py` (which wins) **and** `setup.cfg`; bump both when tagging.

## Decisions

| Topic | Decision |
|---|---|
| `SES_CAMPUS_CONFIG` shape | `{'<campus code>': {'from_email': ..., 'configuration_set': ...}}`; either key optional. |
| Unknown campus / no context | Deployment defaults. |
| Re-saved queue rows (deferred retries) | Already stamped; the stamp is never overwritten. |
| Phase 2 (events) | **Included:** `SESEvent.campus_code` (migration 0005), filled in `save()` by looking up `mail.tags['ses:configuration-set']` in `SES_CAMPUS_CONFIG`; `?campus=` filter on the events API. |
| Removing `'rmu-config-set'` | Done. Local audit: lsco, myce, rvcc, sccc and wnc flush queued mail through `SESBackend` with no explicit set, so today they tag into **RMU's** set. After upgrading they send untagged until they set `AWS_SES_CONFIGURATION_SET`. Called out in the release notes. |

## Review Focus

1. A `from_email` like `"CE Office <noreply@x.edu>"` that equals the default by address → address swapped, display name kept.
2. `X-MyCE-Campus` reaching SMTP through a non-SES inner backend → stripped.
3. A deferred mailer row re-saved outside any campus context → keeps its original campus.
4. `AWS_SES_CONFIGURATION_SET = None` explicitly → no header, no `'None'` string.
5. `SES_CAMPUS_CONFIG` set, but `cis` is not importable → no stamp, no error.

## Tasks

1. `campus_mail.py` (config resolver, stamp, resolve) + `SESBackend` + `RoutingBackend` changes.
2. Queue stamping: `pre_save` on `mailer.models.Message`, connected in `apps.ready()`.
3. Phase 2: `SESEvent.campus_code`, migration, `save()` fill, API filter.
4. Tests (`tests/test_campus_mail.py`) covering every case in the issue plus the Review Focus.
5. README/CLAUDE.md, full suite, commit.
