# Synthetic-only reminder dispatch

## Scope and status

2026-10-20: implemented locally, not deployed. No migration or second scheduler.
Normal dispatch and the existing queue, lease, claim, expiry, provider retry and
Care Task history contracts remain in use. Production Cron stays inactive.

| Requirement | Public owner | Acceptance / environment |
| --- | --- | --- |
| Caller cannot select an account | Dispatcher HTTP boundary | Separate HMAC-bound path; body/query IDs rejected; local HTTP |
| Synthetic account required | Worker composition / queue adapter | Server-configured UUID plus admin-controlled Auth metadata; isolated PostgreSQL |
| No other account projection, claim or maintenance | Queue adapter | Profile selection, sync guards, existing scoped claims and finish ownership; isolated PostgreSQL |
| Existing behavior retained | Normal dispatcher / CLI | Existing HTTP, deployment and reminder regression tests |
| Real device delivery | Hosted Worker/provider/device | NOT VERIFIED; separate deployment, account/device and send approvals required |

## Revised pg_net security assessment

The earlier proposal to revoke platform-owned pg_net ACLs is withdrawn. Supabase
[documents](https://supabase.com/docs/guides/troubleshooting/revoking-access-to-pg_net-objects-has-no-effect-0bbc16)
that per-project grant changes are unsupported and may break pg_net. Keep those
objects, schemas, sequences, functions and grants unchanged.

Read-only checks on the existing project found:

- A Data API request selecting the `net` profile returned HTTP406 / PGRST106:
  the schema is not exposed. No queue contents were returned.
- `anon`, `authenticated` and `service_role` are NOLOGIN.
- No custom LOGIN roles were found; the LOGIN list contains only the known
  platform roles, postgres and authenticator. Their credentials must remain trusted.
- No readable public/graphql_public view dependencies on net/Vault were found.
  Inspection of accessible function sources found one dynamic-SQL candidate,
  `public.rls_auto_enable`, whose return type is event_trigger; it cannot be
  called as a normal Data API RPC. No queue-reading application RPC was found.
  This source/dependency inspection is not a formal proof against arbitrary
  obfuscated future functions. Recheck on new RPCs, exposed schemas or LOGIN roles.

The existing scheduler sends a computed HMAC-SHA256 signature and timestamp,
never the Vault secret. A previous authentication-only rejected probe verified
the deployed Worker and Vault agree, with no dispatch. Signatures are path-bound
and accepted within 60 seconds of server time. There is no nonce replay cache:
an observer with a trusted direct database credential can replay a captured
signature during that window, including repeated work/DoS attempts. Existing
leases, unique queue identities and claim state suppress repeat processing but
do not constitute exactly-once device delivery or replay prevention. A future
timestamp can remain acceptable until timestamp+60s; normal jobs sign current time.
Keep net unexposed; never add generic SQL or queue-reading patient RPCs. HTTPS,
private Vault/Worker secret configuration and trusted DB credentials remain required.

Within those verified boundaries, unsupported ACL changes are not an activation
prerequisite. No production grant or extension change is proposed.

## Minimal implementation

- New fixed path: `POST /internal/notifications/dispatch-synthetic`.
- Same HMAC headers/algorithm/freshness as normal dispatch, but signed message is
  `POST\n/internal/notifications/dispatch-synthetic\n<timestamp>`.
- No account in URL parameters, request body, response or logs. Empty body or
  `{}` only. A normal-path signature cannot invoke the synthetic path.
- Worker-only server configuration: `PUSH_SYNTHETIC_PATIENT_ID`. It is an account
  identifier, not a secret or public frontend setting; keep it out of published logs.
  Unconfigured HTTP mode returns404 and never falls back to global dispatch;
  malformed UUID fails the subprocess safely.
- CLI uses `--synthetic-only`, not a caller-provided patient argument. The selected
  account must have the boolean `demo_only: true` in `auth.users.raw_app_meta_data`.
  This is admin-controlled app metadata, not user-editable user metadata. Setting
  this marker on a real account does not anonymise it: owner verification that the
  account is dedicated and synthetic is a separate mandatory setup gate.
- Account eligibility is rechecked in queue reads/writes. Projection and queue
  maintenance/claim/finish stay within the server-selected account. All enabled
  device subscriptions belonging to that account are in scope, so use only the
  designated test device(s). Normal mode ignores this configuration and is unchanged.
- Existing dispatcher correlation/result logs record synthetic mode and aggregate
  counts; delivery rows and Care Task history remain the persistence/audit evidence.
  No new audit-event type or clinical write is introduced.

## Verification performed

- 76 focused local/mock tests passed: 52 HTTP/subprocess/config, dispatcher,
  Cron-template, deployment-layout and reminder tests plus 24 Render deployment tests.
- 18 real isolated localhost PostgreSQL tests passed: 5 new scoped tests and
  13 existing multiple-reminder/expiry tests. Disposable synthetic accounts;
  actual migrations through034, queue and SQL advisory lease. The scoped HTTP
  test uses actual composition, projection and SQL; its provider/clock/VAPID
  validator are test doubles, not live Supabase Auth or actual Web Push evidence.
- New tests cover missing/false/string-valued admin marker, absent scope,
  cross-account sync/finish, no global HTTP fallback, path binding, stale HMAC,
  rejected client IDs, repeated dispatch, unchanged other-account queue/history.
- An initial fixture failure treated a dictionary as an object; corrected without
  changing production logic. Final selected SQL run passes.
- Ruff checks/format and diff checks passed. Existing Starlette deprecation and
  sandbox pytest-cache warnings remain. No frontend code changed by this task.

Commands (local test infrastructure only):

```powershell
.venv/Scripts/python.exe -m pytest tests/backend/test_synthetic_dispatch.py tests/backend/test_push_dispatch.py tests/backend/test_push_cron.py tests/backend/test_deployment_layout.py tests/backend/test_reminder_delivery.py -q
$env:THREADS_TEST_DSN='postgresql://postgres@127.0.0.1:55439/postgres'
.venv/Scripts/python.exe -m pytest tests/backend/test_synthetic_dispatch_sql.py tests/backend/test_multiple_care_sql.py -q
```

## Deployment requirements — not performed

Owner reviews/commits/pushes the narrow Worker changes and tests. Deploy matching
Worker source before configuring the new mode. No database migration, pg_net ACL,
Vercel Cron or new service is required. Worker environment uses the existing DB,
VAPID and HMAC settings; add only the designated synthetic account configuration.
Existing multiple-reminder feature flags must be coordinated with deployed code
before testing multiple offsets; do not toggle working medication features.

## Exact separately approved production test procedure

1. Keep `medithread-push-minute` absent/inactive. Confirm no other scheduler invokes
   normal dispatch. Do not call `/internal/notifications/dispatch` at any step.
2. Owner designates a dedicated synthetic Auth account and test device(s), verifies
   absence of real patient content, and approves marking its admin app metadata
   `demo_only: true`. Supply its ID through private Worker configuration, not chat.
   Creating/marking the account, subscriptions and test records requires explicit
   approval; none occurred in this task.
3. Owner deploys reviewed source and applies the account configuration. Confirm
   the test mode is available without sending; normal-path signatures must not
   authenticate it, and payload/query account selection must be rejected.
4. Approve a bounded test window, maximum synthetic sends, task IDs and synthetic
   account/device scope. Snapshot aggregate/digest evidence for all other owners.
   Use patient-authorised public Care Task APIs for the synthetic account only;
   create an explicitly labelled task with offsets `[2,1,0]` and due time at least
   three minutes ahead (or supported UI presets over a longer test window).
5. Privately sign an empty synthetic-path request using the existing Vault key
   immediately before each authorised test tick. Do not print/store the secret or
   request headers. Each call uses the existing bounded5-delivery/20s execution.
   Tick at each configured due time; repeat a tick and overlap two authorised
   calls to verify queue identity/lease/dedup. Edit/cancel a second synthetic task
   before a future offset and verify no delivery after cancellation. Check expiry
   without changing production clocks or manipulating real medication records.
6. Check HTTP result, correlation logs, synthetic queue transitions and unchanged
   other-owner digests separately. Provider acceptance is not device receipt:
   owner explicitly confirms the designated device receives/clicks notifications,
   including a closed-browser check. On failure stop; do not invoke global mode,
   disable real subscriptions, retry ambiguous sends or report simulated receipt.
7. Remove the synthetic-account Worker configuration after the bounded test unless
   explicitly retained. Retain audit/queue history; no unapproved deletions.
8. Only after acceptance, separately approve reuse of
   `deploy/dispatcher/push-cron.sql` (creates exactly one initially inactive normal
   minute job), monitoring and `cron.alter_job(...,active:=true)`. This is normal
   production dispatch and needs its own explicit authorisation.

Disable that future job with `cron.alter_job(...,active:=false)`; an already queued
HTTP invocation may still finish. Monitor HTTP responses as well as Cron enqueue
history, queue age, failures and Worker budget/lease saturation. No automated alert
channel was added here. Never blindly replay a timed-out provider send.

## Files in the proposed local change

Runtime: `backend/app/config.py`, `backend/app/transport/dispatcher.py`,
`backend/app/transport/worker_container.py`, `backend/app/infrastructure/dispatch_process.py`,
`backend/app/infrastructure/notification_jobs.py`, `scripts/run_reminders.py`,
`deploy/dispatcher/index.py`.

Tests: `tests/backend/test_synthetic_dispatch.py`,
`tests/backend/test_synthetic_dispatch_sql.py`.

Documentation: this file and additive corrections in `docs/REQUIREMENTS.md` and
`docs/DEFERRED_WORK.md`. Earlier ignored operator proposals are marked withdrawn.
All unrelated frontend/worktree changes are preserved and excluded from this scope.
Proposed future commit: `feat(worker): add server-scoped synthetic reminder dispatch`.
No staging or commit was performed.
