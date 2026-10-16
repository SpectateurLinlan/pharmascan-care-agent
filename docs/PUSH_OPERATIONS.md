# Web Push production operations

This is an operator runbook. SQL blocks are separate approval gates, not a
migration or an instruction to execute the entire document. Do not replay
migrations 001–025. For implementation and safety boundaries see
[REMINDERS](REMINDERS.md).

## 1. Publish and confirm the three services

Local commits do not update hosting. Before an owner-approved push, review all
outgoing commits; Render Auto Deploy can deploy the linked branch on push.

| Service | Entry / root | Production checks |
| --- | --- | --- |
| Frontend `https://medithread.vercel.app` | `frontend/` | `/api/health` proxies to Render; `/sw.js` serves JavaScript from the frontend origin |
| Patient API `https://medithread-patient-api.onrender.com` | repository root; `scripts/run_patient_api.py` | `/api/health`; authenticated `/api/reminders/push/config` |
| Dispatcher `https://medithread-push-worker.vercel.app` | repository root; `[tool.vercel] entrypoint=deploy.dispatcher.index:app` | `/health` returns 200; `/` returns 404; unsigned POST to `/internal/notifications/dispatch` returns 401 |

In each hosting Dashboard, record the Production deployment's source SHA and
successful build. A liveness response cannot reveal the deployed SHA, VAPID pair,
database credentials or subscription configuration. Check key **names/presence**
in the Dashboard; do not export values or paste them into a support conversation.

**Render → patient service → Environment**

- `ENABLE_PUSH_SUBSCRIPTIONS=true`
- `ENABLE_WEB_PUSH=false`
- `VAPID_PUBLIC_KEY`: the public half of the Dispatcher's pair
- `APP_ORIGIN=https://medithread.vercel.app`
- Keep existing Supabase Auth/publishable and patient provider configuration.
- No `DATABASE_URL`, `SUPABASE_SECRET_KEY`, `PUSH_DISPATCH_TOKEN` or
  `VAPID_PRIVATE_KEY`. Do not share an environment group with the Dispatcher.

**Vercel → worker project → Settings → Environment Variables → Production**

- `ENABLE_WEB_PUSH=true`
- `DATABASE_URL`: TLS Supabase **Session Pooler / 5432**, with an owner-reviewed
  least-privilege worker role; not transaction pool / 6543
- `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`
- `PUSH_DISPATCH_TOKEN`: dedicated random ASCII secret, at least 32 characters;
  unrelated to database, Supabase API or JWT keys
- No Gemini, Stage2, patient JWT or frontend `VITE_*` credentials are required.

Changing a hosting environment normally requires a new deployment to take effect;
that remains an owner action. Keep the VAPID pair stable. A changed pair can
require affected devices to unsubscribe and subscribe again.

Log in to the frontend with an existing isolated test identity. Its authenticated
`GET /api/reminders/push/config` must return `available=true`, the expected public
key and `test_available=false`. Compare the public key locally. The direct
patient test sender stays disabled because Render holds no private key. Anonymous
requests without a valid Auth JWT must return 401. Never share the JWT.

## 2. Read-only Supabase preflight

Open the existing project → SQL Editor. This block only reads metadata:

```sql
BEGIN READ ONLY;
SELECT extname, extversion, extnamespace::regnamespace AS schema
FROM pg_extension
WHERE extname IN ('pgcrypto', 'pg_net', 'pg_cron', 'supabase_vault');
SELECT relname, relrowsecurity, relforcerowsecurity
FROM pg_class WHERE oid IN (
  to_regclass('public.push_subscriptions'),
  to_regclass('public.notification_deliveries'));
SELECT tablename, policyname, cmd, roles, qual, with_check
FROM pg_policies WHERE schemaname='public'
AND tablename IN ('push_subscriptions','notification_deliveries');
SELECT count(*) AS matching_signing_secrets
FROM vault.secrets WHERE name='medithread_push_dispatch_hmac';
SELECT jobid, jobname, schedule, active FROM cron.job
WHERE jobname='medithread-push-minute';
ROLLBACK;
```

Expected: `pgcrypto` functions in `extensions`, Cron and Vault installed, both
notification tables enabled/FORCE RLS, owner policies intact, exactly one signing
secret before dispatch. Stop if these differ. The custom
`public.core_schema_migrations` ledger is distinct from Supabase CLI's
`supabase_migrations.schema_migrations`; a missing CLI ledger does not justify
`db push`, migration repair or replaying schema changes.

## 3. Extension and Vault gate — owner approval required

Only if preflight shows `pg_net` missing, approve enabling it in **Database →
Extensions**, or approve this specific SQL. Do not recreate existing extensions:

```sql
CREATE EXTENSION IF NOT EXISTS pg_net WITH SCHEMA extensions;
```

In **Vault → Secrets**, the owner creates `medithread_push_dispatch_hmac` using
the same dedicated value as Vercel's `PUSH_DISPATCH_TOKEN`. Do not paste a real
secret into `vault.create_secret('literal', ...)` in SQL Editor, a Git file or a
Cron command: query text/history can retain it. Do not request or display
`decrypted_secret`. Verify only the name count above.

After extension installation, review actual role visibility:

```sql
BEGIN READ ONLY;
SELECT rolname, rolcanlogin, rolbypassrls,
       has_table_privilege(oid,'net.http_request_queue','SELECT') AS queue_read,
       has_table_privilege(oid,'vault.decrypted_secrets','SELECT') AS vault_read
FROM pg_roles WHERE rolcanlogin
   OR rolname IN ('anon','authenticated','pharmascan_patient');
ROLLBACK;
```

Treat queued headers as readable by database LOGIN roles. Do not attempt to
change Supabase-owned pg_net table ownership, RLS or grants. The long-lived
signing secret must remain restricted to Vault and the isolated worker.
[Supabase header visibility](https://supabase.com/docs/guides/troubleshooting/database-roles-can-read-request-headers-queued-by-pg_net-ad6357),
[grant constraints](https://supabase.com/docs/guides/troubleshooting/revoking-access-to-pg_net-objects-has-no-effect-0bbc16).

## 4. One-shot signed dispatch — separate approval required

This writes to the HTTP queue and can project occurrences/deliveries and send
notifications for **all eligible subscribed patients**. The dispatcher has no
patient-scope parameter. Use an owner-approved quiet window and an isolated
synthetic test patient; review the global impact before approval.

Ensure a device is subscribed, reminders enabled, and a reviewed timed plan has
an occurrence due shortly. The Worker projects the notification queue during
dispatch; an empty queue before its first run is not itself a failure.

The exact signed bytes are `POST\n/internal/notifications/dispatch\n<Unix seconds>`
(UTF-8, no trailing newline). Headers contain only the timestamp and lowercase
hex HMAC-SHA256. The code accepts timestamps within ±60 seconds. There is no
one-time nonce/replay ledger: the same signature can be replayed within this
window. Database advisory locking, atomic claims and delivery state/idempotency
protect sends; they are not request-level replay rejection.

Run only this block after one-shot authorization:

```sql
DO $once$
DECLARE
  signing_key text;
  stamp text;
  signature text;
  request_id bigint;
BEGIN
  SELECT decrypted_secret INTO STRICT signing_key
  FROM vault.decrypted_secrets WHERE name='medithread_push_dispatch_hmac';
  IF length(signing_key)<32 OR octet_length(signing_key)<>length(signing_key) THEN
    RAISE EXCEPTION 'Invalid dispatcher signing configuration';
  END IF;
  stamp := floor(extract(epoch FROM clock_timestamp()))::bigint::text;
  signature := encode(extensions.hmac(
    convert_to('POST'||chr(10)||'/internal/notifications/dispatch'||chr(10)||stamp,'UTF8'),
    convert_to(signing_key,'UTF8'),'sha256'),'hex');
  SELECT net.http_post(
    url := 'https://medithread-push-worker.vercel.app/internal/notifications/dispatch',
    body := '{}'::jsonb,
    headers := jsonb_build_object('Content-Type','application/json',
      'X-Dispatch-Timestamp',stamp,'X-Dispatch-Signature',signature),
    timeout_milliseconds := 45000) INTO request_id;
  RAISE NOTICE 'Dispatcher request ID: %', request_id;
END;
$once$;
```

Expected: exactly one request ID, followed by an HTTP response and worker audit.
The HTTP request is sent after this transaction commits. Do not hold a manual
transaction open. pg_net delay beyond the signature window leads to 401; generate
a **fresh** request only after reviewing the prior response/audit, never reuse an
old timestamp. Missing/duplicate Vault entries fail closed via `INTO STRICT`.

Inspect the returned request ID without dumping request headers or bodies:

```sql
-- Replace 12345 with the returned numeric request ID.
SELECT id,status_code,timed_out,(error_msg IS NOT NULL) AS transport_error,
       coalesce(headers->>'x-request-id',headers->>'X-Request-ID') AS correlation
FROM net._http_response WHERE id=12345;
```

In Vercel **Logs**, correlate `dispatch` / `dispatch_result` with `X-Request-ID`:
200 with `completed` is a completed pass; `busy` sends nothing from that pass;
`budget_exhausted` is partial, not a promise of delivery. `processed` counts
attempts, not device receipts. 401 requires checking the Vault/token match and
clock/delay; 503 requires reviewing worker package, DB and VAPID configuration;
504 is a hard timeout. A send interrupted after claim is uncertain and is not
automatically retried. Preserve queue/audit history; do not reset statuses to
force a retry. No response yet is not proof of failure; check before retriggering.

## 5. Create disabled Cron, then enable — separate approvals

First approve creation of the named job **inactive**. Open and review the complete
[push-cron.sql](../deploy/dispatcher/push-cron.sql), then run that file's SQL in
SQL Editor. It contains the same HMAC command as stage 4, guards against replacing
an existing named job, and disables the new job in the same transaction. No HTTP
request is made by job creation. The job becomes visible only after it is
inactive. Verify exactly one row with the reviewed command, schedule
`* * * * *` and `active=false`. No secret value belongs in the command.

Only after the one-shot and device receipt checks, approve enabling:

```sql
SELECT cron.alter_job(jobid,active:=true) FROM cron.job
WHERE jobname='medithread-push-minute';
```

Observe consecutive runs and one due reminder. Cron `succeeded` means SQL queued
the request, not that HTTP or device delivery succeeded:

```sql
SELECT d.jobid,d.status,d.start_time,d.end_time
FROM cron.job_run_details d JOIN cron.job j USING(jobid)
WHERE j.jobname='medithread-push-minute'
ORDER BY d.start_time DESC LIMIT 10;
```

Rollback, with owner approval, disables only this named job:

```sql
SELECT cron.alter_job(jobid,active:=false) FROM cron.job
WHERE jobname='medithread-push-minute';
```

Disabling prevents future ticks; it cannot cancel a request already queued or a
provider send already in flight. Do not uninstall Cron/pg_net, replay migrations,
delete notifications, alter patient plans or clear Auth. Rotate the dedicated
HMAC secret only under a separate approved credential operation.

## 6. Device acceptance and evidence

Use a synthetic patient's real Application API/B14 activation, never direct SQL
to fabricate clinical state. Recording the subscription, creating the plan,
dispatching and enabling Cron are writes requiring the corresponding approval.

1. On HTTPS, explicitly enable notifications; verify `/sw.js` registration,
   permission `granted`, subscription persistence after reload, and matching
   public VAPID key. iOS/iPadOS requires a supported version and the installed
   Home Screen web app; permission must follow a user gesture.
2. Review/confirm a timed plan due shortly; keep the patient's own IANA timezone
   and reminder preferences. Note no-photo report/B14 remains independent.
3. Run the approved one-shot; correlate HTTP status, dispatcher audit and delivery
   state. Do not infer receipt from provider acceptance or a `sent` row alone.
4. Close the page/PWA, lock/background the device, wait for the approved Cron due
   occurrence, and record the actual device notification/time. Force-stopping a
   browser, disabled OS notifications, offline state and power saving can delay
   delivery. Free/serverless scheduling is not a clinical alarm SLA.
5. Tap the notification. The Service Worker opens the fixed MediThread Today
   route; the current account must authenticate and load only its own records.
   No patient identity or medication details belong in the push payload/URL.
6. With an approved A/B synthetic test, verify account B cannot list/revoke A's
   subscription or read A's dose data. Trigger overlapping/repeated passes and
   check no duplicate successful delivery for the same queue key. Test stop-plan,
   recorded-dose and revoked-device cancellation using approved test objects.
7. Record device/OS/browser, deployment SHAs, due/received times, HTTP correlation
   and result. Keep tokens, endpoint/key material and patient identifiers local.
   Mark Production Live Verified only after actual background receipt **and**
   click/auth/isolation evidence. No automatic SQL cleanup or real-data deletion.
