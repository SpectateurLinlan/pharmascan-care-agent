# Local migrated-feature activation and reminder corrections — 2026-10-19

## Scope and ownership

Owner supplement after production031–033: activate the matching **local** capabilities, correct Today loading/schedule visibility, derive expired-course presentation without lifecycle writes, improve the existing Care Task form, and enforce the original dose attention deadline through Snooze/alerts/Worker. Preserve the existing product identity, enrollment, file safety and navigation architecture.

Public owners: patient FastAPI composition/config and `/api/health`; medication/regimen/Gallery read services; Today attention DTO; Care Task application/RPC contracts; reminder application/Worker queue; calendar export; React presentation. No Stage2, hosted configuration or production patient changes. The new optional `next_due_at`, alert `expires_at`, Care Task `reminder_offsets` and health `multiple_care_reminders_enabled` are additive contracts.

## Runtime and authenticated acceptance

- Local ignored `.env`: `ENABLE_MEDICATION_LIBRARY_FILES=true`, `ENABLE_CARE_TASK_FOLLOWUPS=true`, `ENABLE_LATE_DOSE_REPORTS=true`. Environment variables override the selected env file; safe committed defaults remain false. The actual target is Supabase project `wteaeubvgmheqetmjbml`, whose031–033 application was already separately approved and completed. No migrations were rerun.
- `ENABLE_MULTIPLE_CARE_REMINDERS=false`: requires new034, which is **not applied to production**. Single advance reminders from032 are active. Multiple selection is available only in isolated tests with034 and its separate capability.
- The agent-started local API initially had restricted outbound networking: the same Python Auth settings GET failed with Windows10013 inside the sandbox and returned200 outside it. This was a process network restriction, not proof of logout or missing schema. The replacement API used the same configuration with network access. No invalid-token or unauthenticated probe was counted as patient acceptance.
- The agent-owned8001 process was stopped when the owner requested their normal `python scripts/start_dev.py`; a bind check confirmed8001 available. Do not launch a second server over the owner's existing one.
- **Owner's authenticated browser evidence after normal restart:** `/api/me/medications`200, item_count5; `/api/me/regimens`200; `/api/me/today-attention`200; `/api/reminders/alerts`200. All four Authorization-attached, failure_stage none, diagnostic complete. Previous503 no longer reproduced. No token, identifier or raw patient record was collected. Regimen state counts were not supplied and are not invented.
- `/api/demo/start` was also reported503 during the incident. It was not replayed as a diagnostic because it is a POST that can create a session/profile. Its isolated production-backed success is not claimed.

## Behavior acceptance matrix

| Requirement | Implemented behavior / owner | Direct evidence and boundary |
|---|---|---|
| Existing-data reads with migrated flags | Three flags active; authenticated core reads restored | PASS owner real browser summary above; no patient write tests |
| Today | Next scheduled instant is read-only; current-day state keeps priority; empty/error/loading complete; legacy unreported information remains independent of late-write capability | PASS focused/full local backend/frontend and synthetic EN/ZH browser; actual Today read200, real rendered schedule contents not independently inspected |
| Course dates | Active explicit end before patient-local today derives expired/history, future start derives upcoming, open-ended stays current; actual backend state unchanged | PASS component, backend, browser navigation and isolated occurrence guards; inclusive end-date semantics retained |
| Add Medication | Existing scan/manual actions above current list | PASS actual Chrome at390/768/1280/1920 with synthetic API |
| Care Task form | Primary New opens modal; aligned date/time grid, narrow-screen stack, existing review/past-date/timezone checks | PASS actual390/1280 Chrome screenshots and create/review/persistence journey |
| Advance reminders |032 scalar supports at time,15m,30m,1h,3h,1day/custom | PASS synthetic application/browser; no production task writes |
| Multiple reminders |034 optional normalized array, <=8,0–10080 minutes, owner RLS, optimistic version/idempotency/audit, stable queue slots/cancellation | PASS isolated PostgreSQL and synthetic browser; BLOCKED for real local production-backed use until separate034 approval/application |
| Snooze | Original attention deadline, bounded by next dose/patient day; cannot extend it; successful save quiets stale polls/remount/reload; expiry closes offline | PASS controlled-clock backend/React/Chrome15m/30m; no historical intake inference |
| Cross-tab / error | One sequentially owned local presentation lease, shared quiet time; failed Snooze leaves actionable dialog, records no intake | PASS two actual Chrome tabs with synthetic HTTP. Lease is best-effort localStorage, not an atomic distributed lock for exactly simultaneous claims |
| Worker |15-minute delivery TTL unchanged; original dose deadline additionally enforced; invalid/cancelled task offsets no longer eligible; concurrent sync uses existing unique queue contract | PASS real isolated PostgreSQL. No external send/device receipt claimed |
| Calendar | Private stable UID Care Task VEVENTs, UTC timestamps, supported future VALARMs; existing dose events retained; one-time import | PASS parsed ICS tests. Imported files do not synchronize after edits |
| Library / Push | Existing consent/private-file and comparison safety preserved; delivery configuration truth retained | Real Auth/Storage lifecycle and closed-browser receipt remain NOT VERIFIED/BLOCKED; no production file deletion or provider provisioning |

## Migration034 and rollout gate

`202610190034_multiple_care_reminders.sql` adds nullable `medication_care_tasks.reminder_offsets`, a bounded-array constraint/helper, and replaces the existing create/update functions while retaining owner/version/idempotency/history enforcement and ACLs. NULL preserves scalar fallback; no existing patient rows are backfilled. Worker lateral expansion reuses existing task/subscription/time-slot uniqueness. Removing/changing offsets cancels obsolete pending deliveries; sent deliveries retain their terminal state.

The rollback restores032 function bodies and drops the new objects **only when no task has a multiple-reminder array**. Once multiple reminders are used, do not turn off their reader/Worker capability or use destructive rollback; use a reviewed forward fix. No new external notification infrastructure was added. No production034, Storage, Secrets, Cron, hosted flag or application deployment operation is authorized by this document.

For an eventual rollout: separately review/approve034; apply once with the scoped transactional runner and verify ledger; deploy matching API/Worker/frontend; then enable the new multiple-reminder capability together. Keep the existing three031–033 flags enabled only in environments with those migrations. Real Push additionally needs configured VAPID/subscription/provider/Worker scheduling and actual device receipt; those are separate approvals and acceptance gates.

## Verification records

Evidence files below are ignored local outputs, not public patient records:

- `activation-backend-final.txt`:1133 passed,138 opt-in skips. Synthetic/memory/provider stubs; real SQL cases separately enabled below.
- `activation-frontend-final.txt`:321 passed across56 files.
- `activation-sql034-final.txt`:25 passed, real isolated PostgreSQL55439 with synthetic Auth/storage platform shims, not hosted Supabase Auth/Storage.
- `activation-sql-worker-final.txt`: 32 passed:13 multiple/Worker,4 successor,15 Today/Care cases on real isolated PostgreSQL. The25-case run overlaps; do not add totals.
- `activation-browser-final.txt`:4 passed:cross-tab/error plus 15m/30m stale polling/reload/expiry and multi-reminder form persistence.
- `activation-tabs.txt`:1 passed:second-tab suppression and Snooze503; included again in the final4, not additional.
- `activation-navigation.txt`:2 navigation journeys passed; entry test first failed its required test-origin assertion, then rerun on correct harness.
- `activation-entry.txt`:1 passed against5182 synthetic FastAPI; Add Medication ordering and enrollment preserved.
- `activation-today-browser.txt`:4 passed,1 existing conditional skip against5193 synthetic FastAPI; EN/ZH review/correction/task workflows.
- TypeScript/ESLint/build pass; Vite existing >500KB bundle warning remains. Scoped Ruff/format/diff checks pass. Final form/settings15 tests pass after input validation; these overlap the full suite.

Failures investigated: old expired-course/layout expectations were updated to the new owner supplement; an initial Today next-day priority regression was corrected to preserve today's state; TypeScript caught a missing synthetic `demo_only`; the new SQL boundary fixture initially violated immutable reviewed-source/course guards and was corrected to construct reviewed dates before activation, not disable guards. Source fixtures remain synthetic. No failing clinical guard was weakened.

## Remaining external acceptance

Real Supabase private PDF/photo lifecycle/cleanup remains blocked without an authorized isolated project. Real closed-browser delivery remains unconfigured/unverified. Production034 requires its own approval. Actual patient UI schedule correctness beyond the owner's aggregate read summary needs patient review; no raw records or patient writes are requested for automated tests. Preserve unrelated README/diagrams/catalog maintenance changes outside this task's commits.


## Local commit and reproducible checks

Application/test/optional034 commit: `1fb1245` (`fix(care): activate migrated workflows and bound reminder delivery`). This is a verified local implementation snapshot, not a production034/Storage/Push acceptance claim. Existing7b2d478/2c1acfe/bf3331a/5a1136b are preserved. No Push or deployment.

Commands actually executed (PowerShell; output files under ignored outputs/unified-local-rc):

```powershell
$env:PYTHONPATH='backend'
.venv/Scripts/python.exe -m pytest tests/backend -q --tb=short
$env:THREADS_TEST_DSN='postgresql://postgres@127.0.0.1:55439/postgres'
.venv/Scripts/python.exe -m pytest tests/backend/test_multiple_care_sql.py tests/backend/test_today_care_sql.py tests/backend/test_regimen_successor_sql.py -q --tb=short
# From frontend:
npm test
npm run typecheck
npm run lint
npm run build
$env:QA_BASE_URL='http://127.0.0.1:5193'
npx playwright test e2e/reminder-activation.spec.ts
npx playwright test e2e/today-care-followups.spec.ts
npx playwright test e2e/medication-regimen-history.spec.ts
$env:QA_BASE_URL='http://127.0.0.1:5182'
npx playwright test e2e/medication-entry-management.spec.ts
```

The latest native build exit code is0; the >500KB Vite warning caused a misleading PowerShell redirection error in the first capture, not a failed bundle.19 focused Care/Reminder tests and a later15 form/settings tests overlap the321-case full run; do not add their totals.11 distinct browser journeys pass (4 reminder activation,4 Today/Care,2 navigation,1 entry);1 existing conditional browser case skipped. First SQL fixture failures are retained in diagnostics, with final32-case rerun green and no weakened clinical guards.

Exact application commit file manifest:

- `.env.example`
- `backend/app/application/calendar_export.py`
- `backend/app/application/long_term.py`
- `backend/app/application/personal_gallery.py`
- `backend/app/application/reminder_alerts.py`
- `backend/app/application/reminder_plan.py`
- `backend/app/application/reminders.py`
- `backend/app/application/today_attention.py`
- `backend/app/config.py`
- `backend/app/contracts/long_term.py`
- `backend/app/contracts/today_attention.py`
- `backend/app/infrastructure/care_repos.py`
- `backend/app/infrastructure/notification_jobs.py`
- `backend/app/transport/app_factory.py`
- `backend/app/transport/container.py`
- `backend/app/transport/routes/health.py`
- `backend/app/transport/routes/reminders.py`
- `backend/app/transport/schemas.py`
- `backend/app/transport/worker_container.py`
- `frontend/e2e/medication-entry-management.spec.ts`
- `frontend/e2e/medication-regimen-history.spec.ts`
- `frontend/e2e/reminder-activation.spec.ts`
- `frontend/src/App.tsx`
- `frontend/src/api/care.ts`
- `frontend/src/api/client.ts`
- `frontend/src/components/CareTaskForm.tsx`
- `frontend/src/components/CareTasksScreen.tsx`
- `frontend/src/components/MedicinesHub.tsx`
- `frontend/src/components/PatientApp.test.tsx`
- `frontend/src/components/PatientNavigation.test.tsx`
- `frontend/src/components/PersonalGalleryScreen.tsx`
- `frontend/src/components/RegimenHistoryScreen.test.tsx`
- `frontend/src/components/RegimenHistoryScreen.tsx`
- `frontend/src/components/ReminderMonitor.test.tsx`
- `frontend/src/components/ReminderMonitor.tsx`
- `frontend/src/components/ReminderSettings.test.tsx`
- `frontend/src/components/ReminderSettings.tsx`
- `frontend/src/components/TodayAttentionOverview.tsx`
- `frontend/src/language.tsx`
- `frontend/src/regimenHistoryModel.ts`
- `frontend/src/ui/followups.css`
- `supabase/migrations/202610190034_multiple_care_reminders.sql`
- `supabase/rollback/202610190034_multiple_care_reminders_down.sql`
- `tests/backend/test_medication_evidence.py`
- `tests/backend/test_multiple_care_sql.py`
- `tests/backend/test_patient_app_repairs.py`
- `tests/backend/test_regimen_successor_sql.py`
- `tests/backend/test_reminder_boundaries.py`
- `tests/backend/test_unified_release_sql.py`
- `tests/backend/today_care_browser_server.py`
