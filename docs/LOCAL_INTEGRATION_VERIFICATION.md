# Final local integration verification - 2026-10-19

## Current decision and scope

This dated supplement supersedes the earlier split Release A/B execution plan. The owner requested one unified local integration and categorized local commits, stopping before Push. No separate schema030 release, deployment SHA investigation, production migration or deployment was performed. Earlier evidence remains historical, not erased.

**Local integration: PASS. Production migration/unified deployment: NO-GO.** There is no confirmed authorized isolated Supabase project; real Auth/PostgREST/Storage, protected-source Storage retention, upload/deletion recovery and hosted/device acceptance are not proven. Local commits are reviewed implementation snapshots, not a production-readiness claim.

`7b2d478 fix(regimens): unify course records and gallery status` is present and unchanged. Foundation commit: `2c1acfe fix(core): make migrations atomic and preserve auth and agent boundaries`. Feature commit: `bf3331a feat(care): integrate medication files, care tasks and late-dose reports`. The final verification/documentation commit follows these.

## Behavior acceptance matrix

| Owner requirement / public boundary | Actual outcome and evidence | Status / environment |
|---|---|---|
| Regimen Records and Gallery consistency; existing patient-scoped routes | Existing All Courses/current/ended chain semantics retained; two genuine Back/Forward/direct-refresh flows pass | PASS local Chrome, synthetic Auth/HTTP |
| Medication Detail -> product files -> All Files -> Back/Forward/refresh; photo detail history | Full previously failing journey now passes, including no uncaught page errors | PASS local Chrome, synthetic Auth/HTTP |
| Periodic Summary shows fetched counts and details | Existing corrected assertion checks labeled `Patient reported taken: 2`, not a nonexistent standalone `2`; full frontend passes | PASS component, mocked API |
| Library PDF/photo lifecycle and comparison boundary | Owned DTOs, evidence-only safety, duplicate handling, retirement/audit/protected associations, PDF preview/edit/delete UI covered | PASS local/mock and isolated SQL; real Storage BLOCKED |
| Today/Care/report correction and reminders | EN/ZH confirmation, editing, task links, capability-off behavior, no-current-medication follow-ups; queue deduplication/early-claim rejection and corrected effective events checked | PASS synthetic HTTP/Chrome and isolated SQL; actual notification receipt NOT VERIFIED |
| Atomic migration runner and ordered031 -> 032 -> 033 | Actual scoped runner, advisory transaction lock, exact hashes/prerequisites, ledger failure rolls back DDL, repeat/concurrent submission safety | PASS isolated PostgreSQL |
| Auth and patient isolation; Agent RESTORE | SDK existing-session diagnostic, 401 versus identity outage503, current-record resolution and ambiguity refusal; cross-owner requests rejected | PASS local/mock plus SQL roles; hosted Auth BLOCKED |

## Failure diagnoses and fixes in this final round

1. The old History browser assertions used Treatment history/terminal-only counts. `7b2d478` and the remaining current test updates use Regimen Records and actual confirmed course-chain tips. No lifecycle rows were changed to satisfy the test.
2. Medication Detail's broad `getByText('Not recorded').first()` selected the hidden, deliberately mounted Regimen Records date row. Scope the assertion to its visible Medication information region.
3. The extended detail journey still asserted Reference photos/All galleries after the approved Medication Files/All Files rename. Correct those exact labels without removing navigation assertions.
4. That older fixture also returned its catch-all `{}` for GET `/api/evidence/gallery/DEMO-med/files`. This is not the actual backend DTO; it crashed rendering on `.filter`. Supply actual file arrays/metadata and assert the complete journey has no page errors. No backend records or functioning route code were replaced with mocks.
5. The Summary test's old standalone-number expectation was stale: SummaryOverview renders counts in meaningful labeled text. Its existing worktree fix was verified by319 full frontend passes; no Summary production source changes were required.
6. Additional enrollment regressions used an incomplete accessible button name, assumed a pending card before any draft existed, or ignored the unsaved-exit confirmation overlay. Tests now check the real accessible name, both absent/created-draft pending states and their placement, and explicitly confirm departure. Both actual synthetic-API journeys pass; deletion/confirmation checks remain.

The first over-broad browser invocation used the wrong test origin for diagnostics/enrollment. Correct harnesses were used on rerun:5173 diagnostic,5182 grouped-records server,5193 Today/Care. Today confirmation mutates synthetic fixtures, so only this task's server was restarted before the final fresh run. No timeout increases, forced clicks, weakened consent, new skip, or patient-data changes were used.

## Actual verification

Evidence files are private ignored local outputs under `outputs/unified-local-rc/`; no tokens, patient rows, traces or screenshots are committed.

| Command / evidence | Result | Scope |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest tests/backend -q` / backend-final.txt |1129 passed,128 opt-in skipped | Full local backend; SQL/provider cases without explicit credentials skipped, not counted as real infrastructure |
| `npm test -- --reporter=dot` / frontend-final.txt |319 passed /56 files | Full frontend component/unit |
| `pytest test_unified_release_sql.py test_library_lifecycle_sql.py -q`, explicit local55441 / sql-final.txt |34 passed (unified8 +03126) | Real PostgreSQL17.11; Auth/Storage schemas are shims |
| `pytest test_today_care_sql.py -q`, explicit local55439 / sql-care-final.txt |15 passed | Real PostgreSQL032/033/RLS/RPC/queue/concurrency/rollback |
| `pytest test_regimen_successor_sql.py -q`, local55439 / sql-successor-final.txt |4 passed | Real PostgreSQL030 atomic activation/preservation/ACL/rollback |
| `pytest test_release_a_schema030.py test_library_release_compatibility.py -q`, local55441 / compatibility-final.txt |19 passed (2 real SQL composition cases and17 unit/mock) | Compatibility regression only, not a separate release |
| Playwright detail/records/library/Today/Care/history-unavailable, fresh5193 / browser-final.txt |17 passed,1 environment-specific skip | Actual Chrome/React; mocked HTTP or actual synthetic memory FastAPI. That skipped case ran separately below |
| Playwright ended-plan follow-up, dedicated no-active server / browser-ended-final.txt |1 passed | Actual synthetic FastAPI/Chrome |
| Playwright SDK diagnostic onlocalhost5173 / browser-auth-final.txt |3 passed | Actual SDK/browser, mocked identity/API |
| Playwright entry-management/confirmation-gate on5182 / browser-entry-final.txt |2 passed | Actual synthetic FastAPI/Chrome; four responsive widths |
| Foundation staged-index snapshot focused tests / foundation-snapshot-tests.txt |50 passed | Exact selected snapshot without uncommitted feature dependencies |
| After one whitespace-only Gallery formatting correction: evidence/library/Today backend / feature-focused-final.txt |61 passed | Focused local/mock regression; overlaps full backend |
| `npm run typecheck`, `npm run lint`, `npm run build` |PASS | Vite large-chunk warning retained |
| Ruff check, touched Python format and staged diff/privacy checks |PASS after one condition-line formatting correction | No broad reformat; staged private-key/JWT checks zero matches; three DSN matches verified as explicit DEMO literals in offline-only target tests |
| `check_supabase_test_target.py --env-file .env.supabase-test` |BLOCKED before connecting | Missing/inconsistent isolated configuration; production never substituted |

There are53 distinct migration/integrated PostgreSQL cases plus2 schema-compatibility PostgreSQL cases; do not add overlapping full/component/focused counts. There are23 distinct passing browser journeys across the four final browser rows. Earlier wrong-port SQL startup failures were harness failures, corrected by explicit loopback ports and verified data directories before the passing reruns. Full backend/frontend evidence is reused after a whitespace-only Python formatting change; affected61 tests were rerun. Browser and SQL environment retries are not fabricated first-attempt success.

## Migration execution, compatibility and recovery

Local environment: existing isolated PostgreSQL17.11 clusters on127.0.0.1 ports55441/55439, disposable databases and synthetic users only. Unified test verifies the55441 data directory equals `outputs/incident031/pgdata`, bootstraps001-030, then executes the actual CLI scoped031 -> 032 -> 033 with one ledger/DDL transaction per migration. All33 ledger hashes match. A deliberately failed031 ledger insert rolls back all031 objects, followed by an explicitly inspected successful application. RLS/ACL, audit rollback, idempotency/concurrency, protected sources, embedding retirement, effective correction reads and worker capability composition pass.

No production ledger was refreshed this round. Prior read-only evidence reported027-030 applied and031-033 absent; it must be rechecked immediately before any future authorized execution. Existing030 files are now versioned as prerequisites, not replayed.031,032,033 define separate business features; chronological runner intentionally requires earlier exact ledger hashes, so do not bypass031 to apply032 or manipulate the ledger. Do not use generic `supabase db push` with the custom `core_schema_migrations` ledger.

Storage remains a separate release blocker: deterministic retry keys and pending-delete receipts are locally tested, but cross-service upload/register ambiguity can leave private orphan objects. There is no indiscriminate cleanup. Real owner RLS, private PDF/photo bytes, protected-source retention under Storage policies, delete retry/restore and concurrent database/Storage races require authorized isolated Supabase testing. Basic PDF signature/EOF checks are not parsing or malware scanning. Parser/scanner/quota/backup-and-restore requirements remain in Medication Library readiness. About's PDF understanding remains future capability; its EN/ZH browser check passes.

## Owner actions and eventual production/Push sequence -> NOT EXECUTED

1. Review these commits and the exact path manifests below. README/diagrams/catalog maintenance and unrelated evidence tooling remain uncommitted. Do not accidentally add them to this release.
2. Configure a genuinely separate Supabase test project in Git-ignored `.env.supabase-test` (see Medication Library readiness guide); do not send secrets in chat. Provide only the local path and authorize synthetic tests against the named test project. Close real Auth/Storage/retention/recovery gates before requesting production approval.
3. Independently approve the exact production migration operation after current ledger/hash checks and fresh DB plus Storage recovery readiness. Do not assume a DB backup contains Storage bytes. Review rollback guards: nonempty clinical/file audit tables require forward repair, not destructive automatic rollback.
4. Once authorized and ready, use the reviewed runner with the operator's explicitly verified production configuration: `python scripts/db.py status`, then `python scripts/db.py migrate --only 202610190031`, inspect ledger/objects/ACL, then similarly032 and033, then `python scripts/db.py verify`. Stop on failure or ambiguous connection loss; inspect state before retrying. Do not repeat030 or silently alter hashes/ledger. These commands are a future plan, not executed here.
5. Coordinate the same reviewed backend and worker source before capability enablement and matching frontend. Keep `ENABLE_MEDICATION_LIBRARY_FILES`, `ENABLE_CARE_TASK_FOLLOWUPS`, `ENABLE_LATE_DOSE_REPORTS` false until their schema and actual integration checks pass. Once033 report data exists, all history/summary/Alerts/worker readers must preserve effective corrections; disabling the reader or reverting to raw events is not a safe rollback.
6. Inspect source-trigger settings yourself before Push. Repository has Render `autoDeployTrigger: commit`, frontend Vercel API rewrite and independent dispatcher configuration, but no `.github/workflows` directory; Dashboard branch bindings are not verified here. A Push may trigger deployments. Do not assume GitHub CI orchestrates migration/backend/worker/frontend ordering. No Push is recommended while production gates remain open.
7. Eventual manual review commands: `git log -5 --oneline`, `git diff 7b2d478..HEAD --stat`, `git show --stat <each-new-SHA>`, `git status --short`. If the named branch and deployment consequences are approved: `git push --dry-run origin HEAD:feat/agentic-ux-landscape`, then personally `git push origin HEAD:feat/agentic-ux-landscape`. Do not merge to main implicitly or include uncommitted maintenance.
8. Hosted acceptance after separately approved releases: authenticated Current Medications/Regimen Records/Gallery/Alerts/dose history statuses and actual outcomes; genuine Back/Forward/refresh; Today confirmations/corrections; Care Task reminder timing/dedup/Snooze; private file bytes and protected deletion; cross-owner refusal; audit/effective-history consistency. Output counts/statuses only through the existing safe diagnostic, never tokens/raw records. Hosted Auth/Storage and physical notification receipt are NOT VERIFIED here.

## Exact committed path manifests

The following lists are generated from each reviewed local commit. They do not include private test outputs.

### 2c1acfe

```text
backend/app/agent/read_dialogue.py
backend/app/infrastructure/postgres_migrations.py
backend/app/infrastructure/supabase_data.py
backend/app/transport/auth.py
scripts/db.py
supabase/migrations/202610190030_regimen_successor_activation.sql
supabase/rollback/202610190030_regimen_successor_activation.sql
tests/backend/test_auth_provider_failures.py
tests/backend/test_correctness02_dialogue.py
tests/backend/test_regimen_successor_sql.py
```

### bf3331a

```text
.env.example
backend/app/application/dosing.py
backend/app/application/enrollment.py
backend/app/application/late_reports.py
backend/app/application/library_files.py
backend/app/application/long_term.py
backend/app/application/personal_gallery.py
backend/app/application/record_history.py
backend/app/application/review_summary.py
backend/app/application/source_preview.py
backend/app/config.py
backend/app/contracts/care_calendar.py
backend/app/contracts/dto.py
backend/app/contracts/late_reports.py
backend/app/contracts/library_files.py
backend/app/contracts/long_term.py
backend/app/contracts/medication_evidence.py
backend/app/contracts/ports.py
backend/app/contracts/record_history.py
backend/app/infrastructure/care_repos.py
backend/app/infrastructure/evidence_repos.py
backend/app/infrastructure/late_report_repos.py
backend/app/infrastructure/library_files.py
backend/app/infrastructure/memory_repos.py
backend/app/infrastructure/notification_jobs.py
backend/app/infrastructure/postgres_repos.py
backend/app/infrastructure/record_history.py
backend/app/infrastructure/supabase_repos.py
backend/app/transport/app_factory.py
backend/app/transport/container.py
backend/app/transport/routes/evidence.py
backend/app/transport/routes/health.py
backend/app/transport/routes/late_reports.py
backend/app/transport/routes/medications.py
backend/app/transport/schemas.py
backend/app/transport/worker_container.py
frontend/src/App.test.tsx
frontend/src/App.tsx
frontend/src/api/auth.test.ts
frontend/src/api/auth.ts
frontend/src/api/care.ts
frontend/src/api/client.ts
frontend/src/api/diagnosticContract.ts
frontend/src/api/doseFollowUps.ts
frontend/src/api/localDiagnostics.test.ts
frontend/src/api/localDiagnostics.ts
frontend/src/components/BottomSheet.tsx
frontend/src/components/CareFollowUps.test.tsx
frontend/src/components/CareReviewSheet.tsx
frontend/src/components/CareTaskForm.tsx
frontend/src/components/CareTasksScreen.tsx
frontend/src/components/EnrollScreen.tsx
frontend/src/components/FollowUpError.tsx
frontend/src/components/HistoryFilters.test.tsx
frontend/src/components/HistoryScreen.tsx
frontend/src/components/InventoryPanel.tsx
frontend/src/components/LateDoseFollowUps.tsx
frontend/src/components/LongTermCare.test.tsx
frontend/src/components/MedicationEvidence.test.tsx
frontend/src/components/MedicationLibraryFileManagement.test.tsx
frontend/src/components/MedicationLibraryFileManagement.tsx
frontend/src/components/MedicinesHub.tsx
frontend/src/components/PatientHub.tsx
frontend/src/components/PatientNavigation.test.tsx
frontend/src/components/PersonalGalleryScreen.tsx
frontend/src/components/PhotoAcquisition.test.tsx
frontend/src/components/PhotoAcquisition.tsx
frontend/src/components/PrivateEvidencePhoto.tsx
frontend/src/components/RecordSemantics.test.tsx
frontend/src/components/ReminderMonitor.test.tsx
frontend/src/components/ReminderMonitor.tsx
frontend/src/components/TodayAttentionOverview.test.tsx
frontend/src/components/TodayAttentionOverview.tsx
frontend/src/components/VisualCheckScreen.test.tsx
frontend/src/components/VisualCheckScreen.tsx
frontend/src/components/followUpCopy.ts
frontend/src/components/primitives.tsx
frontend/src/language.tsx
frontend/src/main.tsx
frontend/src/navigation.test.tsx
frontend/src/navigation.ts
frontend/src/patientDateTime.ts
frontend/src/ui/app.css
frontend/src/ui/components.css
frontend/src/ui/followups.css
frontend/src/ui/primitives.tsx
frontend/src/vite-env.d.ts
supabase/migrations/202610190031_medication_library_file_lifecycle.sql
supabase/migrations/202610190032_care_task_followup_ux.sql
supabase/migrations/202610190033_late_dose_reports.sql
supabase/rollback/202610190031_medication_library_file_lifecycle_down.sql
supabase/rollback/202610190032_care_task_followup_ux_down.sql
supabase/rollback/202610190033_late_dose_reports_down.sql
tests/backend/accept_release_gallery.py
tests/backend/conftest.py
tests/backend/test_enrollment.py
tests/backend/test_gallery_upload_validation.py
tests/backend/test_medication_evidence.py
tests/backend/test_medication_library_files.py
tests/backend/test_medication_understanding.py
tests/backend/test_record_history_adapter.py
tests/backend/test_supabase_data.py
tests/backend/test_supabase_live.py
tests/backend/test_today_care_followups.py
```

### Verification boundaries and retained work

The23 listed browser journeys are the executed final set. Older opt-in real Gemini/Stage2/Supabase and device journeys were not run; their naming updates are preserved without claiming provider acceptance. Existing React act warnings, Starlette deprecation, Vite chunk-size and local pytest-cache permission warnings remain non-failing. No general file-catalog/diagram/README maintenance tests were run as release evidence.

Only this task's local synthetic servers/clusters are stopped at exit; pre-existing user5173 and8001 services are preserved. External infrastructure readiness still requires the owner's isolated project, storage retention/recovery decision and separate production approvals.

### Final verification/documentation commit - reviewed path scope

```text
docs/DEFERRED_WORK.md
docs/RELEASE_MIGRATION_RECOVERY.md
docs/REQUIREMENTS.md
frontend/e2e/companion.spec.ts
frontend/e2e/correctness02-choices.spec.ts
frontend/e2e/enrollment-refinement.spec.ts
frontend/e2e/gallery-evidence.spec.ts
frontend/e2e/gallery-thumbnails.spec.ts
frontend/e2e/long-term-care.spec.ts
frontend/e2e/medication-entry-management.spec.ts
frontend/e2e/medication-persistence.spec.ts
frontend/e2e/medication-regimen-history.spec.ts
frontend/e2e/medithread-rc.spec.ts
frontend/e2e/patient-experience.spec.ts
frontend/e2e/records-confirmation-gate.spec.ts
frontend/e2e/records-history-unavailable.spec.ts
frontend/e2e/session045.spec.ts
frontend/e2e/stage2-v010.spec.ts
frontend/e2e/ux-consistency.spec.ts
frontend/e2e/ux-navigation.spec.ts
frontend/e2e/ux-polish-a1.spec.ts
docs/AUTHENTICATED_BROWSER_DIAGNOSTIC.md
docs/CARE_CALENDAR_INTEGRATION.md
docs/INTEGRATED_RELEASE_CANDIDATE.md
docs/LOCAL_INTEGRATION_VERIFICATION.md
docs/MEDICATION_LIBRARY_RELEASE_READINESS.md
frontend/e2e/auth-diagnostic.spec.ts
frontend/e2e/medication-detail-refinement.spec.ts
frontend/e2e/medication-gallery-refactor.spec.ts
frontend/e2e/today-care-followups.spec.ts
scripts/qa/check_supabase_test_target.py
scripts/qa/inspect_library_release.py
scripts/qa/medication_counts_in_browser.js
tests/backend/test_library_lifecycle_sql.py
tests/backend/test_library_release_compatibility.py
tests/backend/test_release_a_schema030.py
tests/backend/test_supabase_test_target.py
tests/backend/test_today_care_sql.py
tests/backend/test_unified_release_sql.py
tests/backend/today_care_browser_server.py
```
