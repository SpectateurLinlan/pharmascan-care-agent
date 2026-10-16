# Reminders and notifications

## Protected dispatcher and device setup (local implementation)

The worker-only ASGI factory is `app.transport.dispatcher:create_dispatcher_app`.
It is a separate deployment/environment, never mounted in patient FastAPI and
never a frontend target. `NotificationDispatchService` is the common application
pass for CLI and HTTP. The existing plan projection, queue, SQL eligibility,
atomic claims and finish/retry semantics remain authoritative. No schema change.

After deliberately configuring worker secrets, its local entry is:

```sh
PYTHONPATH=backend python -m uvicorn app.transport.dispatcher:create_dispatcher_app --factory --host 127.0.0.1 --port 8026
```

Only `POST /internal/notifications/dispatch` exists. It accepts empty body or `{}`,
no query, no Origin, no arbitrary patient, destination, command or batch size.
Authentication uses a dedicated server-only `PUSH_DISPATCH_TOKEN` (at least32
random ASCII characters), HMAC-SHA256 and a60-second timestamp window:

```text
message = "POST\n/internal/notifications/dispatch\n" + unix_timestamp_seconds
X-Dispatch-Timestamp: unix_timestamp_seconds
X-Dispatch-Signature: lowercase_hex_hmac_sha256(secret, utf8(message))
```

Never use a Supabase API secret, JWT signing key, database password or user JWT
as the scheduling secret. No bearer fallback. Configure accurate server clocks.
Replies contain only status/counts and a correlation ID, with no-store headers.
Missing/bad/stale signature401; unsupported input400; unavailable503; timeout504.
The fixed child process receives5-delivery/20-second cooperative bounds. Its
parent kills/waits after25seconds; it is not a detached/background task. Database
connection and statement timeouts bound individual operations. A session advisory
lock spans projection and sending across concurrent CLI/HTTP workers. Overlap
returns `busy`; a later fresh Cron invocation can retry. A hard interruption after
claim remains uncertain and is not automatically replayed as successful delivery.
Use a direct/session-pooled DSN (Supabase IPv4 session pool port5432 if needed),
NOT a transaction-pooled connection: session advisory locks need stable backend
session affinity. The worker rejects the common transaction-pool port6543 before
connecting. Verify any custom proxy's pooling mode too; the port check cannot
prove arbitrary proxy behavior. Short-lived request connections are closed on
completion/kill. No pool/database setting is changed automatically.
No provider credentials, subscription keys, raw provider responses or patient IDs
are logged by the dispatcher. Host/platform access logs must also omit credentials.

CLI keeps `--loop`, with default50 deliveries per pass and the same20-second
cooperative budget. It does not provide the HTTP parent's hard process deadline.
The current500-profile cap and finite scheduling window are demo-scale limits,
not throughput/SLA promises. Monitor backlog and budget exhaustion before expanding.

Patient APIs add `POST /api/reminders/push/current` (validated browser subscription
input; owner-scoped id/enabled response) and `POST /api/reminders/push/test`
(`subscription_id`, UUID `request_id`; verified owner only). Config adds
`test_available`. Test credentials are read via the same-user JWT repository;
the browser never selects the owner or receives stored keys. Tests send generic
diagnostic content directly, never fabricate a dose/task queue row, record intake,
change a regimen or exercise B14. Explicit tests have a bounded per-process
60-second cooldown/replay cache. This is NOT a cross-instance durable idempotency
guarantee for diagnostics; do not automatically retry uncertain tests. Clinical
scheduled notifications retain existing database-wide deduplication. Provider
acceptance does not verify device receipt. Expired test subscriptions are revoked.

Me → Settings → Medication reminders now separates reminder preference, browser
permission, current owned subscription, server key configuration and unverified
scheduled delivery. It includes current-device enable/off, individually labelled
account-device revocation, explicit test, refresh and a persistent Windows/Android/
iOS/macOS guide. Saved device ids reveal no endpoint/key; device labels are ordinal,
not verified device names. A one-time owner/browser invitation follows UI activation;
Later/Guide dismiss it and no system permission is requested without Enable.

### Deployment decision and human configuration gate

Prefer a **separate Vercel Python worker project**. Set its Root Directory to the
repository root (`.`), with `deploy/dispatcher/index.py` as the ASGI entry selected
by `[tool.vercel].entrypoint = "deploy.dispatcher.index:app"` in `pyproject.toml`. That project
has its own environment-variable scope; never share privileged worker secrets with
the patient FastAPI project. The three logical services remain frontend, patient
API and isolated dispatcher. The dispatcher starts one short-lived worker child
per authorized request, never a permanent loop.

Local Vercel preflight files are `.python-version` (3.12), the existing
`pyproject.toml` runtime dependencies (including pywebpush, required by the worker
adapter), and `vercel.json` (Singapore `sin1`, 60-second function max, explicit inclusion of
`backend/app/**` and `scripts/run_reminders.py`, development-tree exclusions), and
`.vercelignore` (public runtime source allowlist). `deploy/dispatcher/index.py` exposes only the existing
dispatcher app, adds the bundled `backend` source directory to Python's import
path, and derives/injects the project-root path from its own source location.
The function's bundle patterns use compact brace globs: Vercel limits each
`includeFiles` / `excludeFiles` string to 256 characters. Keep `.vercelignore`
for the upload allowlist as well; the function glob separately excludes frontend,
hidden files/directories, credentials and generated assets. Unlisted root paths
are not uploaded; public configuration does not enumerate local-only materials.
No `PYTHONPATH` setting is required. No patient API,
Agent, Gemini, Stage2, voice or migration entrypoint is exported by this project.
Leave Build Command and Output
Directory at Vercel's auto-detected defaults; there is no frontend build.

The repository-wide `pyproject.toml` also declares patient API packages such as
Gemini and Pillow that this dispatcher does not import. Vercel's Python bundler
does not tree-shake unused Python dependencies; although the documented uncompressed
limit is 500 MB, this exact bundle size has not been measured. Preview must report
the produced bundle size and cold-start behavior before this is accepted. If the
bundle is too large or slow, stop and add a separately verified worker dependency
manifest/build profile before deployment rather than deleting patient API dependencies.

Vercel announced Python GA on 2026-10-15; current Python 3.12/3.13/3.14 are
supported. The installed Vercel CLI is 54.4.1 (the FastAPI guide requires 48.1.8+).
Fluid compute Hobby allows up to300seconds per Function and 2GB/1vCPU; this
project explicitly sets60seconds, safely above the existing25-second child hard
timeout. The standard Python bundle limit is500MB. Hobby includes4 active CPU
hours,360GB-hours provisioned memory and1M invocations monthly. Supabase Cron,
not Vercel Cron, provides the minute schedule: Vercel Hobby Cron is limited to
once per day. Published allowances do not guarantee this worker's usage fits or
that notifications arrive on time.

There is no shared local file lock across Vercel instances. The existing queue
coordinates across instances with a PostgreSQL session advisory lock over the
projection/send pass, `FOR UPDATE SKIP LOCKED` atomic claims, and stable unique
keys/status transitions for occurrence/device/slot. The owner confirmed the
Supabase IPv4 Session Pooler on5432; session mode preserves the advisory lock.
Transaction pool6543 remains rejected. Vercel does not share local files between
instances, which is immaterial to this design. Pooler credentials/permissions/TLS,
function-to-child termination and cold-start latency still require Preview smoke.

This Windows environment has Vercel CLI54.4.1, but `vercel dev --local` could not
build the Python function: local runtime bootstrap could not locate `uv` (`spawn
python3 ENOENT`), and the CLI update worker hit a sandbox-denied user-cache write.
No account was linked and no deployment occurred. Therefore the Vercel bundle and
subprocess path are **prepared but not locally build-verified**. Current Vercel
Python documentation supports ASGI, `pyproject.toml`/`requirements.txt`, and bundle
controls, but does not promise this exact child-process workload. Confirm the first
Preview build and protected invocation before creating Cron. If Vercel cannot run
and reap the bounded child reliably, use Render's normal Python process model as
fallback; Render Free sleeps after15minutes idle, wakes slowly and shares750 monthly
instance hours, so it cannot promise minute-level reminder timing.

Render Free is the fallback standard Python web service, using the same factory
with `--host 0.0.0.0 --port $PORT`. It supports the normal Python process model,
but sleeps after15minutes idle, can take about1minute to wake, and shares750 free
instance hours/workspace/month. Two continuously running free services exceed
that allowance. Never create a charged service or assume cron traffic guarantees
availability. See [Vercel Python](https://vercel.com/docs/functions/runtimes/python),
[function limits](https://vercel.com/docs/functions/limitations),
[Vercel resource quotas](https://vercel.com/docs/functions/usage-and-pricing) and
[Render Free](https://render.com/docs/free). One minute Cron means about43200
requests/30days; CPU/memory/egress and the main app also consume quotas. No free
tier guarantees alarm delivery. Owner must review live quotas before deployment.

Configuration boundaries:

| Runtime | Public configuration | Server-only secrets |
| --- | --- | --- |
| Frontend | VITE_SUPABASE_URL, VITE_SUPABASE_PUBLISHABLE_KEY | None |
| Patient FastAPI | AUTH_MODE=supabase, PERSISTENCE=supabase, APP_ORIGIN, SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, ENABLE_DEMO_SEED=false, ENABLE_WEB_PUSH=false, ENABLE_PUSH_SUBSCRIPTIONS=true, VAPID_PUBLIC_KEY | Existing Gemini/provider secrets only; NO VAPID_PRIVATE_KEY, DATABASE_URL or PUSH_DISPATCH_TOKEN |
| Worker Dispatcher | ENABLE_WEB_PUSH=true, VAPID_PUBLIC_KEY, VAPID_SUBJECT | DATABASE_URL (IPv4 Session Pooler 5432), VAPID_PRIVATE_KEY, PUSH_DISPATCH_TOKEN |
| Supabase Vault/Cron | fixed Dispatcher HTTPS URL, schedule, HMAC message format | same dedicated PUSH_DISPATCH_TOKEN, NOT VAPID/database/admin keys |

The isolated Vercel project's fixed endpoint is
`https://<worker-domain>/internal/notifications/dispatch` because its FastAPI
entrypoint is at the project root. `GET /health` is an unauthenticated liveness
probe only; it returns no configuration and never connects to the database or
push provider. An unsigned POST to the dispatch path must return401 without
invoking the worker. Neither check verifies database readiness or device receipt.

The Dispatcher needs the VAPID pair and operator subject. The patient API needs
only `VAPID_PUBLIC_KEY` with `ENABLE_PUSH_SUBSCRIPTIONS=true`; it must keep
`ENABLE_WEB_PUSH=false` and must never receive the private key, worker database
URL or dispatch token. The public key must match the Dispatcher's private key;
that pairing is verified during a real-device delivery test. Since the old direct
diagnostic test requires the private key, `test_available=false` on Render and
the patient UI disables that button. Test scheduled delivery through the queue.
No Gemini, Stage2 or speech credentials are needed by the Worker. Generate the
real pair only after owner approval with `python scripts/create_vapid_keys.py`;
it exclusively writes ignored `outputs/local-vapid.env` and prints no keys. Store
the private key in server secret stores, preserve the pair across restarts, use
an operator-controlled subject, and transfer the dedicated scheduling secret to
Vault independently. No real runtime key was generated during this implementation.

Prefer an operator-reviewed dedicated worker DB login with only the required
business-read/occurrence/queue/subscription privileges. If the existing DSN is
`postgres`/BYPASSRLS, its broader access is a deployment risk requiring owner review;
this patch neither creates roles nor grants permissions. Never use that credential
as a Cron signing key or put it in the patient runtime.

### Supabase pg_net credential visibility: mandatory operator check

Cron Integration is owner-confirmed installed, with no Job. HTTP scheduling uses
`pg_net` in addition to `pg_cron`; inspect its actual installation/role privileges
before enabling. The official guidance says database LOGIN roles can read queued
headers; Vault does not hide a decrypted value once queued. Project-level REVOKE
attempts on Supabase-owned pg_net tables may have no effect. Do not try to change
their ownership/RLS or claim those headers are private. Keep `net` OUT of exposed
Data API schemas, review all LOGIN roles and avoid logging request headers.
Our HMAC design queues only a short-lived signature, not the long-lived secret;
replay within60seconds cannot change destination/payload and existing queue/lease
still controls clinical writes. A compromised trusted DB login remains a risk.
References: [queued header visibility](https://supabase.com/docs/guides/troubleshooting/database-roles-can-read-request-headers-queued-by-pg_net-ad6357),
[platform grant constraints](https://supabase.com/docs/guides/troubleshooting/revoking-access-to-pg_net-objects-has-no-effect-0bbc16).

Owner-only procedure, after explicit approval: Dashboard → Integrations → Cron;
Database → Extensions to inspect pg_net/pgcrypto; Vault to store the dedicated
secret; SQL Editor to review a single named Cron Job. In scheduled SQL, read the
secret from Vault into a local variable, form the current Unix-seconds timestamp,
then compute `encode(hmac(convert_to(message,'UTF8'), convert_to(secret,'UTF8'),
'sha256'),'hex')` using pgcrypto. The message is exactly the method/path/timestamp
above. Pass only the timestamp and resulting short-lived signature to
`net.http_post` headers; never put the long-lived secret in headers, cron command
text, responses, logs or public config. Keep the URL fixed in reviewed SQL, body
`{}`, timeout45000ms. The signature remains replayable within its60-second window;
it authorizes only this fixed bounded dispatch, while database idempotency prevents
duplicate delivery rows. Run each minute only
after manual one-shot acceptance. Check actual extension function schemas and
access; never paste a long-lived key into cron.job.command. Cron/pg_net submission
success is not HTTP success: inspect pg_net response code and safe Worker logs too.
No SQL is automatically applied by app startup and no Cron Job is created here.

#### Production SQL and device acceptance (operator action only)

Use [PUSH_OPERATIONS](PUSH_OPERATIONS.md) for the current service URLs,
environment boundaries, read-only preflight, Vault configuration, one-shot
signed request, response inspection, inactive Cron creation, separate activation
and rollback. The complete [inactive-job SQL](../deploy/dispatcher/push-cron.sql)
contains no signing secret and refuses to replace an existing named job.
The pgcrypto function schema must match the actual database. Neither the
runbook nor the SQL file is executed by application startup or migrations.

Rollback: disable only the named Job, turn off runtime, revoke/rotate only the
dedicated signing secret. Preserve clinical queues/history. Do NOT uninstall
pg_cron (removes unrelated jobs), drop pg_net (can break webhooks), reset the DB,
repair migration history or delete patient subscriptions en masse.

Supabase Dashboard/CLI uses `supabase_migrations.schema_migrations`; this project
uses `public.core_schema_migrations` with source hashes through its own runner.
An empty Dashboard history does not imply missing business tables. Read/compare
both ledgers and schema first; never auto-run `db push`, `migration repair` or
reapply021–024. Owner confirms both Push tables have ENABLE/FORCE RLS and the
owner policy; no table/policy/migration changes are included in this patch.
See [Supabase migration history](https://supabase.com/docs/reference/cli/supabase-migration-list).

Acceptance after hosting: permission → SW active → owner subscription persisted →
explicit diagnostic provider acceptance → visible real device notification →
click/auth/Today, with no intake event. Then test a synthetic reviewed timed plan
while the page is closed, duplicate/concurrent Cron, stop/cancel, retry/revoke,
logout and A/B isolation. Physical iOS/Android/macOS/Windows receipt remains
AWAITING LIVE DEVICE VERIFICATION; code is IMPLEMENTED LOCAL, awaiting hosting.

Targeted local commands (no external providers; do not enable Live flags):

```powershell
$env:PYTHONPATH='backend'
python -m pytest tests/backend/test_push_dispatch.py tests/backend/test_reminder_delivery.py -q -p no:cacheprovider
npm --prefix frontend test -- src/webPush.test.ts src/serviceWorker.test.ts src/serviceWorkerPush.test.ts src/components/PushNotificationSettings.test.tsx src/components/ReminderSettings.test.tsx src/App.test.tsx src/components/MedicationEvidence.test.tsx
```

For the opt-in browser fixture, start Vite on an unused localhost port with blank
VITE_SUPABASE_URL/VITE_SUPABASE_PUBLISHABLE_KEY, then from `frontend/` set
`RUN_PUSH_LOCAL=1`, `QA_BASE_URL` to that local origin and run
`npx playwright test e2e/web-push-local.spec.ts`. All HTTP business I/O is mocked;
Chrome registers the actual service worker but creates no real Push subscription.
Screenshots carry a visible LOCAL/MOCK label. This does not verify device receipt,
Supabase RLS or a hosted Dispatcher. Existing cloud tests remain opt-in.

## Current implementation

Medication-related care tasks now share the existing delivery queue and worker. Migration022 adds an alternate owned task reference with task/device/time deduplication. `PostgresNotificationJobs.sync_tasks` projects confirmed open/deferred dates; claim rechecks current task date/status, subscription and reminder preference. Completed/cancelled/deferred-old-date jobs are cancelled; stopped/ended plans suppress derived supply jobs. There is no new scheduler or Gemini timer. In-app Today follow-ups use the existing reminder presentation refresh signal and an idempotent supply reconciliation endpoint. See [long-term care](LONG_TERM_CARE.md). Care-task SQL queue/claim/cancel is real tested with a fake endpoint and deliberately uncertain simulated send; real device delivery remains NOT VERIFIED.

P0 automatic reminders use reviewed, explicitly activated regimen versions and their persisted dose rules/occurrences. `ReminderPlanService` is the common projection for the settings list, calendar and independent worker. Existing `ReminderAlertService` supplies due in-app prompts; existing `dose_reminders` retains explicit snoozes. No Agent timer, inferred clock time, prescription change or intake write is involved.

The patient can enable/disable reminders and choose 0–120 lead minutes in **Me → Medication reminders**. New plan versions replace future projected reminders after review/activation; stopping a recorded plan preserves history and removes it from the projection. PRN and incomplete/unactivated plans produce no fixed reminders. A frequency such as “twice daily” still needs patient-confirmed clock times. Meal wording does not authorize an invented “30 minutes after food” instruction.

Rule timezones remain attached to the confirmed version. New rules use the patient's validated IANA timezone; changing a display preference does not silently retime existing instructions. UTC instants are generated from local wall time, including weekday/course filters. Nonexistent DST times are skipped; a repeated wall time is generated once using the first occurrence. Patients needing a different DST policy should review a new plan with their professional instructions. No missed-dose inference or compensating dose is created.

## P1 Web Push

```text
Explicit Enable Web Push → browser permission → /sw.js + PushManager
→ same-user JWT FastAPI subscription API → owner RLS

Independent supervised worker / external scheduler
→ existing regimen/rule/occurrence projection → notification_deliveries
→ atomic SKIP LOCKED claim + live eligibility check → encrypted Web Push
→ service worker → private generic notification → /#today
→ normal authentication / RLS / B14
```

Migration **021** adds `patient_profiles.reminders_enabled`, `push_subscriptions` and `notification_deliveries`. Both new tables use FORCE RLS. Patients can manage their subscriptions; delivery records are owner-readable with **no patient DML grant**. Normal patient APIs continue to use the same-user access token. The explicit administrative worker uses `DATABASE_URL` separately; it is never a patient-request fallback or Agent tool.

Subscriptions are validated, limited to eight enabled devices/account, and restricted to supported HTTPS push-provider endpoints. Worker input is revalidated even if a record was inserted directly through the Data API. Redirects are disabled. Keys/endpoints/provider bodies are not logged or included in list responses. Notification content contains no name, medicine, dose or diagnosis; the click target is fixed to this app's Today route. The service worker caches no records or authenticated responses.

Jobs bind owner, regimen, rule, occurrence and subscription. The stable `(occurrence, subscription, slot)` key prevents duplicate scheduled deliveries; an explicit snooze gets its own slot. Current preference, active regimen, enabled rule/subscription, closed occurrence, dose event and effective/course dates are checked again at claim. Obsolete/expired pending jobs are cancelled. Provider 404/410 disables a subscription; 429/503 uses bounded backoff (maximum three attempts). Numeric Retry-After is bounded; an unparseable HTTP-date is conservatively deferred. Failed/uncertain sends are never reported as delivered. A send interrupted after acceptance is marked uncertain rather than blindly replayed. A notification already accepted or in flight cannot be recalled after a plan change.

`sent` means the push provider accepted the request, **not that the device received or displayed it**. Browser retries, offline devices, OS policy and power management can delay or suppress delivery. Do not use this prototype as a guaranteed alarm.

### Configuration and startup

Install worker dependencies:

```powershell
python -m pip install -e ".[dev,push]"
python scripts/create_vapid_keys.py
```

The generator writes only Git-ignored `outputs/local-vapid.env`, refuses to overwrite it, prints no keys and leaves delivery disabled. Transfer the generated pair into the server's private configuration; set `VAPID_SUBJECT` to an operator-controlled `mailto:` or HTTPS contact. Keep the same pair across restarts. Never place the private key or `DATABASE_URL` in `VITE_` variables. Apply migration021 using the normal migration workflow.

```dotenv
ENABLE_PUSH_SUBSCRIPTIONS=false
ENABLE_WEB_PUSH=false
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_SUBJECT=
```

After deliberate configuration, set `ENABLE_PUSH_SUBSCRIPTIONS=true` on the
patient API with only the public key. Set `ENABLE_WEB_PUSH=true` only on the
isolated Dispatcher with the private key, subject and worker database URL. For
local worker checks, run:

```powershell
python scripts/run_reminders.py
# Or a supervised process while running locally:
python scripts/run_reminders.py --loop
```

Default is one bounded pass; `--loop` polls every 30 seconds. An external scheduler may invoke the one-pass command once/minute. Running the local process is not a hosted scheduler deployment. Free hosting may sleep or lack durable jobs. No hosted service was enabled in this task. The current bounded worker visits at most500 subscribed profiles/pass and sends at most50 jobs/pass; larger installations need paging/sharding and retention policy.

Permission is requested only after explicit Enable. The UI preloads server configuration to preserve the browser user gesture. Missing configuration/unsupported devices remain visibly unavailable. Denial leaves records, in-app reminders and calendar export usable. Current-device subscriptions are revoked before app sign-out; failure is shown, rather than claiming cleanup succeeded. Other devices can be disabled from settings. An expired Auth session never grants notification links access to patient data.

Use HTTPS for deployment (localhost is suitable for development). Windows Chrome/Edge and Android Chrome PWA require browser/OS permission and an active subscription. On iPhone/iPad, Web Push requires iOS/iPadOS16.4+ and a web app added to the Home Screen; ordinary Safari tabs are not equivalent. See [WebKit platform requirements](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/) and [PushManager subscription options](https://developer.mozilla.org/en-US/docs/Web/API/PushManager/subscribe). Device reception and notification click acceptance remain separate manual gates.

## P1 calendar export

**Me → Medication reminders → Add to Calendar** downloads an actual authenticated `.ics` file. It expands a finite maximum31-day window (UI:30days), capped at500 events, within the effective course and supported weekday rules. UTC timestamps preserve each rule's local-time/DST conversion. Stable occurrence-derived UID, CLASS:PRIVATE and a generic “Review medication plan” title avoid exposing drug names. VALARM uses the confirmed lead time; explicit snoozes use their requested reminder time. PRN/incomplete plans cannot create fixed events. See [iCalendar RFC5545](https://www.rfc-editor.org/rfc/rfc5545).

This is a **one-time import**, not live synchronization or an Alarm Clock API. After editing/stopping a regimen, patients must update or delete old imported calendar events. UID stability does not guarantee that Apple/Google/Outlook will replace previous imports. Actual calendar-client import and alarm behavior are MANUAL PENDING.

## Verification and manual acceptance

Tests classify local/mocked provider results separately from real Supabase/JWT/SQL. No real external Push was sent by automated tests. Screenshots are synthetic local browser evidence in `outputs/ux-integration/`.

- [ ] Configure VAPID and a supervised HTTPS runtime/worker, then enable on a test device.
- [ ] Verify service worker active, system permission granted and subscription saved as separate steps.
- [ ] Activate a synthetic timed plan; close the page and verify a real provider-accepted delivery **and** visible device receipt.
- [ ] Click notification; confirm Today opens with normal Auth/RLS, without recording intake.
- [ ] Test denied permission, device disable/sign-out, plan replacement/stop and multi-device behavior.
- [ ] Import the downloaded calendar into an actual calendar client; check time, lead alarm and manual removal of old events.

## P2 future native applications

Future Android/iOS applications may integrate Android Alarm/Reminder APIs and iOS AlarmKit or applicable reminder APIs, with explicit permission, user review, update/delete synchronization and suitable offline support. No native alarm integration, React Native/Flutter migration or second app is implemented here.

## Reproducible acceptance checklist

Session04.5 keeps this single scheduling/delivery implementation. Assistant now opens over its source page; confirmation sheets remain separate portals and notification clicks still require current Auth and confirmation. The header shortcut and Me reminder entry open the same settings. No new notification provider or native alarm was introduced.

1. Restart current backend/frontend with `python scripts/start_dev.py`; retain the existing Auth/browser storage.
2. A new owner sees the Guide. Click blank/header/tabs, press Escape, switch apps and refresh: current step stays. Use explicit Skip/Finish; replay from Me > Help.
3. Switch four root tabs repeatedly: no root Back. Open Assistant from Today/Medicines/Records, type a draft and return; the draft stays. Open a medication, edit a new reviewed version and Back to detail. Photo result Back returns to acquisition, then origin.
4. Add a synthetic timed plan, review and activate. Set lead minutes so it becomes due soon. Verify the in-app reminder and correct medicine; no intake event appears. Replace the reviewed version or explicitly stop the recorded plan; old future reminders disappear. Check PRN/incomplete plans produce no fixed reminders.
5. Download `.ics`, inspect its private title and import into a real calendar client. Check local time/alarm/course window; after changing the plan, remove stale imported events manually.
6. Configure VAPID, HTTPS and a supervised independent worker before enabling Web Push. Authorize a real test device, close the page, verify provider acceptance/device receipt/click independently. Denial must leave the app usable. Check iOS Home Screen requirements.

Browser evidence folders are local-only: `outputs/ux-integration/` (Chrome) and `outputs/ux-integration-edge/` (Edge). They include hover, 390/430/1280px settings, automatic prompt, Chinese150% Today/Guide and explicitly **MOCK** missing-reference result navigation. The visual-navigation fixture is not a real Stage2 result. Actual current tests use `RUN_LOCAL_UX=1 QA_BASE_URL=<isolated URL> npx playwright test e2e/ux-navigation.spec.ts`; real providers remain opt-in.
