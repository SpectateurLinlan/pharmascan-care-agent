# Medication Library incident and migration 031 readiness — 2026-10-19

> **Latest 2026-10-19 owner scope and verification:** [Final local integration](LOCAL_INTEGRATION_VERIFICATION.md). Unified local commits supersede the earlier split-release plan below; production remains NO-GO. Earlier evidence is retained as history.


**Decision: NO-GO for production migration/file-lifecycle release.** The reported incident is local development code connected to the existing production Supabase project, not an established Vercel/Render incident. The owner explicitly clarified the origin as `http://localhost:5173`. No production remediation, migration, schema-cache refresh, Storage change, deployment or Git publication was performed.

## Acceptance and execution recovery

| Behavior / current owner source | Owner / public boundary | Verified outcome | Scope / remaining gate |
|---|---|---|---|
| P0 incident dependency diagnosis | FastAPI routes, Supabase adapters, local launcher | PASS for source/config/catalog diagnosis | Real authenticated patient counts are NOT VERIFIED; no browser session is available to automation |
| Restore schema030 compatibility without new migrations | Explicit configuration and request-scoped composition root | PASS local/mock | Real patient browser confirmation pending; new031/033 capabilities remain off |
| Missing-object errors and failed-read presentation | Data adapter, ErrorNotice, library | PASS local/mock | No deployed fix claimed |
|031 SQL/RLS/RPC/audit/concurrency/rollback | Migration031 and disposable PostgreSQL17.11 | PASS — real PostgreSQL,26 tests | Local auth/storage schemas are platform shims, not real Supabase Auth/Storage |
| PDF/photo application and browser flows | Authenticated FastAPI contracts and typed UI client | PASS local/mock | Real authenticated Storage BLOCKED; no isolated project configured |
| General release regression | Typecheck/lint/build and frontend suites | Focused tests PASS; full Vitest FAIL | Two unrelated Today/Care Task integration tests remain stale |
| PDF security and cross-service recovery | Private Storage, lifecycle registration | PARTIAL | See restrictions and unresolved risks below |

Before interruption, the metadata investigation, explicit capability flags and first031 corrections existed. A real SQL run had13 passes/3 failures. After resuming, those16 tests passed; coverage expanded to26, including embedding retirement and association/deletion concurrency. No old implementation was restarted. Earlier memory/browser evidence remains historical and is not promoted to real infrastructure evidence.

An initial attempt to reuse localhost55439 failed during connection setup. A new dedicated cluster at localhost55441 was initialized from the existing PostgreSQL17.11 binaries. Every SQL test creates a disposable database, applies001–030 then031, uses synthetic owners and drops that database. No production DSN is accepted by this fixture.

## A. Incident diagnosis

### Environment and release evidence

- Local branch: `feat/agentic-ux-landscape`; HEAD `60ae19ab1553bda99e614fcace8c3a72db175222`. Feature work remains uncommitted and is not represented by that SHA alone.
- Local5173 forwards API traffic to8001. Local8001 OpenAPI contains files/PDF/late-report endpoints. Source configuration checks confirm that the backend Supabase URL, database project identity and frontend Supabase URL refer to the same project; no identity/credential values were printed.
- Public Render OpenAPI did **not** contain the local files/PDF/late-report endpoints. A public frontend-proxied health request returned200. Render's first health probe timed out; its subsequent OpenAPI probe returned200. These facts establish neither authenticated health nor the deployed Git SHA.
- Public GitHub main/status reported `d6d9874cf807fadb220255aeff5d1bd2c3792ebd` and successful Vercel checks dated2026-10-18. A check attached to a commit is not proof that the production alias still serves it. Vercel CLI lacked existing credentials; its unsolicited login flow was stopped without completing login. Active Vercel/Render SHAs and deployment timestamps remain NOT VERIFIED and are no longer prerequisites for diagnosing the clarified local incident.
- Catalog checks used an explicitly read-only transaction (`transaction_read_only=on`), inspected no patient rows and made no changes.001–030 are recorded;027–030 match local files using the established runner's normalized UTF-8 hashing.031–033 are absent. `medication_library_files`, `effective_dose_events` and `dose_report_entries` are physically absent, so a cache reload cannot create them.

| Endpoint / feature | Observed error | Confirmed dependency and diagnosis | Smallest safe correction | Evidence / limit |
|---|---|---|---|---|
| `/api/evidence/gallery` | Local422, `INVALID_INPUT`, downstream404/PGRST205 | New route unconditionally added PDF counts by reading `medication_library_files` (031), which is absent | Default031 capability off; preserve existing image/source aggregation | Local route/OpenAPI/config + actual catalog; authenticated repaired browser journey pending |
| `/api/reminders/alerts` | Local422 with same downstream error | Reminder service calls event `find_by_occurrence`; new generic event repository targeted `effective_dose_events` (033), absent. Existing `dose_reminders` (007), core occurrence/rule/regimen tables (001) and preferences (001/008) exist | Explicit033 reader opt-in; schema030 reads `dose_events`; keep polling with bounded failure backoff | Source and catalog confirmed. No031 dependency. No authenticated production alert probe was run |
| `/api/me/medication-history` | Owner reported422 | Scheduled history unconditionally queried `dose_report_entries` (033), absent; legacy reads use `dose_occurrences` and `dose_events` | Query amendments only when033 is explicitly enabled | Confirmed dependency defect; no original endpoint-specific error body was retained |
| `/api/me/medications` | No supplied authenticated failure response | Active-regimen list uses existing patient medications, regimens and sources; no031/033 query in this route | Retain existing contract; don't equate a failing Detail gallery/history panel with a list failure | Synthetic HTTP200. Actual patient item_count NOT VERIFIED |
| `/api/me/regimens` / Regimen History | Owner expected more cards | API returns regimen versions; history projects only terminal `ended`/`superseded` chain tips. An active successor hides its superseded predecessor as the same course. Draft/pending/active rows are not terminal history | Preserve version/course distinction and stable medication IDs; no record mutation | Synthetic component/browser regression PASS. Actual patient state distribution remains unknown |
| `/api/me/dose-follow-ups` | Owner supplied `PROVIDER_UNAVAILABLE`, `Dose report follow-ups are unavailable`, from Today dose reports | New033 feature is intentionally not constructed when its capability is off | Keep unavailable until its separate033 release gate passes; do not enable033 as an incident workaround | Source literal and owner-provided response identify the formerly unknown error |

The former422 was an adapter defect: missing tables/columns/functions were labelled patient input errors. The adapter now maps42P01/42703/42883/PGRST202/204/205 to the existing503 `PROVIDER_UNAVAILABLE` envelope. Logs retain only method, allowlisted resource name, provider code/status; they omit query filters, request/response bodies, tokens and patient identifiers. Actual input/business validation still uses422; authentication stays401/403; existing conflict codes are preserved.

Alerts previously polled every15 seconds, with an in-flight guard but no persistent-failure backoff. It now retries after15/30/60/120 seconds, retains the in-flight/visibility/modal guards and resumes15-second polling after success. No Snooze-expiry or duplicate-reminder repair is inferred from this change. **GET Alerts can materialize future occurrences:** it was not called with a real patient token during this read-only investigation.

The library no longer shows "no medications" or registration instructions after a failed read. Pending031 write controls are hidden unless the typed file response explicitly reports `file_management_available=true`; existing photo upload, source browsing, private images, navigation and legacy comparison retirement remain available.

One additional presentation risk remains outside this correction: MedicinesHub uses a past planned end date to omit an otherwise active API row from Current Medications, while history correctly excludes non-terminal active rows. Thus such a row can be absent from both lists. This is a confirmed code path, **not a confirmed explanation for this patient's missing medicines**; no real regimen data was read or reclassified. History search currently supports medication display name only because its API supplies no brand/ingredient/strength fields. Separate genuine courses are not merged by name.

### Actual local restart and patient-count boundary

The owner subsequently authorized only the local API restart and aggregate reads. Process ancestry identified the existing `scripts/start_dev.py` supervisor, whose documented default is API reload enabled. Python edits triggered its API-only restart; the listener PID changed and the existing5173 frontend stayed running. No second launcher/frontend was started.

The restarted real API `/api/health` returned200 with both:

```text
medication_library_files_enabled=false
late_dose_reports_enabled=false
```

These additive, non-sensitive health fields come from the same injected configuration as the patient factory. Environment names are `ENABLE_MEDICATION_LIBRARY_FILES` and `ENABLE_LATE_DOSE_REPORTS`, defined in `backend/app/config.py` and documented in `.env.example`. The actual `.env` was not edited.

No existing patient JWT/test-session credential was configured in the local environment and no accessible browser debugging session existed. Existing opt-in live tests create anonymous users and synthetic clinical records, so they were **not** used against production. Unauthenticated local GETs to both requested endpoints returned401; patient `item_count`/state counts are NOT VERIFIED, not zero and not synthetic substitutions.

Minimum browser verification: keep the already signed-in `http://localhost:5173` tab open, open DevTools Console, and paste [the local count script](../scripts/qa/medication_counts_in_browser.js). It reads the existing SDK session only in that browser, calls exactly the two requested GETs and prints only endpoint/status/item_count/state counts. It never prints a token, patient ID, medication name or record body; it performs no login/session-refresh/save operation. If no single current session exists, it refuses. Share only its summary table, never Network request headers or Storage contents.

## B. Migration031 audit and remaining gates

### Objects and dependencies

- Three new patient-owned tables: `medication_library_files` (identity, explicit medication/source/regimen FKs, storage key, checksum, original/display names, category/description, PDF MIME/size, timestamps/version/tombstone/cleanup/demo fields); `medication_library_file_audit`; `medication_image_audit`.
- Composite owner FKs enforce patient scoping. Unique patient/medication/checksum and global storage key protect duplicate metadata. PDF size1–10MiB, checksum, category, MIME, title/description and patient-rooted path checks are present. Source/regimen FKs remain separate entities; an uploaded PDF does not invent enrollment/source/regimen links.
- Owner/date partial file index and image-storage-reference expression index. All three tables ENABLE/FORCE RLS and allow authenticated owner SELECT; direct patient INSERT/UPDATE/DELETE/TRUNCATE are denied.
- PDF RPCs: register, versioned metadata update, confirmed tombstone and cleanup acknowledgement. Photo RPCs: versioned manage edit/remove/delete, cleanup acknowledgement and replacement of existing retire-reference RPC. Public/anon/service-role execution is revoked for these seven patient RPCs; authenticated execution is retained. SECURITY DEFINER functions pin search_path and validate the acting owner.
- Existing image-update trigger uses a replaced guard. A new before-insert storage-reference trigger and advisory transaction lock serialize new associations with photo tombstoning; cross-owner paths and associations to tombstoned objects are rejected.
- Audit distinguishes upload/edit/delete, remove-from-gallery and stopped-comparison. Embeddings retire transactionally; private evidence/reference-set/history rows remain. Rollback refuses if any new file or lifecycle-audit table contains rows; empty-only rollback restores the older retirement guard/RPC and removes031-only objects.
- Direct prerequisites are001/003/015/018 and privilege tightening029.031 does not call030's successor RPC, but the chronological runner requires the complete matching001–030 ledger. No031 dependency on032/033 exists. The rollback changes no patient lifecycle state.
- Supabase CLI's migration ledger is absent; the existing project uses `public.core_schema_migrations`. **Do not use `supabase db push`: it can consider already-applied custom-runner migrations pending, as well as include unrelated032/033.**

The unpublished031 file was corrected locally after real SQL failures: image checksum/storage keys reside in JSON rather than physical columns; null optimistic versions must be rejected; stopped-comparison must be permitted by its audit CHECK; retirement must delete embeddings. The added association/tombstone lock closes the tested shared-image insert race. No applied001–030 file was edited by this task.

### Real PostgreSQL verification

26 tests PASS on PostgreSQL17.11, fresh schema001–030 plus031. Coverage: UP; empty rollback/reapply; repeated SQL application fails without damaging existing objects; positive/negative constraints; effective function ACLs under simulated hosted function defaults; direct-write denial; owner read/RPC isolation; duplicate/concurrent registration; same bytes across owners; stale/null versions; concurrent edits; source-linked deletion rejection; shared-image deletion rejection; insert/tombstone race; four embedding-retirement paths; preservation of evidence/reference-set rows; audit-failure transaction rollback; tombstone retries/acknowledgements; nonempty rollback refusal.

This is actual PostgreSQL execution with locally shimmed Supabase platform schemas. It is not proof of PostgREST JWT role switching, hosted Storage behavior or physical-device behavior.

### Storage, recovery and PDF safety

- **BLOCKED — real authenticated Supabase Auth/Storage.** No authorized isolated project/configuration was found. No production image/PDF was uploaded, fetched or deleted for testing.
- Read-only production metadata confirms `medication-sources` is private, but its bucket size/MIME restrictions are null. Existing owner policies allow SELECT/INSERT/UPDATE/DELETE on owner-rooted paths; they do not enforce library tombstones or protected source retention. Application deletion protections do not establish that direct owner Storage calls obey the same retention policy. Any policy tightening must preserve approved enrollment/draft cleanup and needs a separately reviewed proposal/approval.
- PDF validation checks MIME, extension,10MiB limit, header and final EOF marker. Filenames are normalized without losing `.pdf`; deterministic patient/medication/checksum keys use no-upsert uploads. Responses include no-store, nosniff, Content-Disposition, CSP sandbox and same-origin resource policy. Blob/native PDF viewer behavior is still distinct from raw response headers.
- These checks are **not full PDF parsing, script sanitization or malware scanning**. No upload-specific rate/quota control or scanner was demonstrated. General real-user uploads remain NO-GO pending an explicit restricted-release threat assessment and the required controls. PDF OCR/clinical interpretation remains future work.
- Upload order remains Storage then registration. A new metadata preflight avoids uploading known active duplicates or recreating a known tombstone. Ambiguous registration failures are logged without object paths and are never compensated by a blind delete. Tests prove same-key retry converges both when registration committed and when it did not.
- An abandoned first upload can still leave a private orphan; there is no durable reservation/reconciliation queue. A delete racing an in-flight PDF upload also spans two services and is not fully serialized by the metadata transaction. Minimum next design: durable owner-scoped upload reservation/status, stable operation ID and a bounded reconciler that verifies no committed/protected reference uses the key before cleanup; never sweep a whole bucket. This requires separately reviewed state/API/RPC work and real Storage race tests.
- Database backup evidence from030 does not include Storage object bytes. No verified Storage restore/recovery procedure exists for the proposed deletion release. Retain NO-GO for deletion until this is resolved.

Actual About UI already contains PDF Prescription Understanding in the future roadmap. A new EN/ZH browser assertion verifies its "not available yet" wording and distinguishes original upload/display from future OCR, structured extraction, patient confirmation and enrollment. No new model call was added.

## C. Recommended release path

**Option A now: local compatibility with schema030; no production migration.** Keep both new database feature switches false. The request graph uses existing dose events and image/source records, while031/033 implementations remain available for their separate releases. The restarted local API confirms these settings. This is safe only for a schema without033 correction data: after033 data exists, turning its reader off or returning to raw events can hide corrections and is not an acceptable rollback.

**Option B later:031 plus coordinated application release.** Still NO-GO because real Storage, retention, reconciliation, recovery and full-worktree regression gaps remain.031 alone cannot fix033 dependencies and must not be approved as an Alerts workaround. **Option C: defer PDF/photo lifecycle production release** while preserving the already working photo/source library; recommended until gates close.

1. Isolate a reproducible release scope from the dirty worktree. Do not publish the whole workspace or include Care Tasks/032/033, enrollment/history changes or worker queries merely because they share files. No new release commit exists yet.
2. Complete isolated Auth/PostgREST/Storage verification and security/recovery gates. Review the exact031 artifact/hash again if it changes. Check a fresh read-only ledger immediately before any approved application.
3. If031 is separately approved later, the established scoped command is `python scripts/db.py migrate --only 202610190031` using the approved production configuration. **Prepared only, not executed or approved.** The current runner commits DDL before recording its custom ledger; a ledger-write failure can leave applied DDL without a record. Review this window before execution. On any failure stop, preserve metadata, inspect actual objects/ledger and request the precise recovery operation; never rerun blindly or automatically roll back.
4. Database031 precedes enabling `ENABLE_MEDICATION_LIBRARY_FILES=true` on a separately approved Render release. Leave `ENABLE_LATE_DOSE_REPORTS=false` unless the separate033 release is approved/ready. No Storage policy change is silently bundled.
5. Release the reviewed backend contract before Vercel frontend changes. Verify health/capabilities/OpenAPI and actual release SHAs. Use staged synthetic authenticated patients for list/regimen/history/gallery/navigation/Alerts/file lifecycle smoke; verify patient isolation, duplicate/error/retry behavior, private previews, source protection and unchanged comparison eligibility.
6. Production authenticated smoke is independently scoped: use existing authorized identities and read-only endpoints. Alerts GET may materialize occurrences, so do not call it under a claimed read-only production check. Actual production file/dose transitions need their own approval.
7. Recovery: before031 has data, the reviewed empty-only rollback is test-proven; coordinate API/client compatibility and ledger handling explicitly. After any031 file/audit data exists, prefer a forward repair preserving evidence. Do not run its guarded rollback destructively. For code-only Option A, restore the preceding reviewed release/configuration without touching patient rows. Hosted rollout/rollback remain unapproved.

## Isolated Supabase setup requested by the owner

An independent hosted Free project is the simplest available way to finish real Auth/Storage verification here; it is not the only option. A complete local Supabase stack also includes Auth/PostgREST/Storage but requires Docker-compatible tooling, which was unavailable. Bare PostgreSQL alone cannot close the Storage gate.

Manual owner steps:

1. In Supabase Dashboard choose a **Free-plan organization**, create a new clearly named test project and keep production untouched. Current official documentation allows two active Free projects in total; check your account's remaining allowance. Do not upgrade or provision a paid project for this task. Free projects with low activity may be paused.
2. Store the test URL, publishable key and test database connection/password in a new private `.env.supabase-test`; never paste credentials into chat. Use a different database password and project identity. Keep a separate patient-runtime configuration without database/admin/worker credentials. These `.env.*` files are already Git-ignored.
3. Add `APP_ENV=test`, `AUTH_MODE=supabase`, `PERSISTENCE=supabase`, and explicit `TEST_PROJECT_REF` to the test configuration. Tell Codex only its local file path and authorize tests against that named isolated project. Use synthetic users/files only; do not clone production patient data or Storage bytes.
4. Before writes, run `python scripts/qa/check_supabase_test_target.py --env-file .env.supabase-test`. The offline checker refuses the normal project identity, mismatched project/database targets, transaction pooling and administrative patient API keys. It prints only a fingerprint; it does not connect or provision anything. It is a preflight, not an execution guard: the actual future test runner must revalidate the same configuration/JWT issuer before each write.

Once that project exists and is authorized, Codex can prepare isolated configuration, verify target separation, bootstrap only the reviewed001–031 schema, create synthetic A/B identities, and run the authenticated lifecycle/race tests. This was **not** done now. A fresh-project bootstrap must explicitly cap at031; the current unscoped folder includes032/033. Hosted account creation, billing choices and secret entry remain owner actions.

Official references: [Free billing](https://supabase.com/docs/guides/platform/billing-on-supabase), [Free project pausing](https://supabase.com/docs/guides/platform/free-project-pausing), [local full-stack development](https://supabase.com/docs/guides/local-development), [Storage upload limits](https://supabase.com/docs/guides/storage/uploads/file-limits), [PostgREST errors](https://docs.postgrest.org/en/v16/references/errors.html).

## D. Repository and actual verification

Task-owned edits (earlier unrelated changes in these files are retained):

- `.env.example`; `backend/app/config.py` — explicit031/033 release flags, default off.
- `backend/app/infrastructure/supabase_data.py` — missing-object503 mapping and scrubbed diagnostics.
- `backend/app/infrastructure/supabase_repos.py`; `backend/app/infrastructure/record_history.py`; `backend/app/transport/container.py` — explicit compatible readers/service composition; preserve opt-in033 behavior.
- `backend/app/transport/routes/evidence.py` — capability projection, disabled-feature guards and private PDF headers.
- `backend/app/application/library_files.py` — preflight/tombstone protection, retry diagnostics, EOF/filename validation.
- `backend/app/transport/app_factory.py`; `backend/app/transport/routes/health.py`; `backend/app/transport/schemas.py` — non-sensitive effective feature readout.
- `frontend/src/api/client.ts`; `frontend/src/components/PersonalGalleryScreen.tsx`; `frontend/src/components/ReminderMonitor.tsx` — additive typed capabilities, error-versus-empty handling, feature controls and failure backoff.
- `supabase/migrations/202610190031_medication_library_file_lifecycle.sql`; its matching guarded rollback — local SQL fixes only.
- New `tests/backend/test_library_lifecycle_sql.py`, `test_library_release_compatibility.py`, `test_supabase_test_target.py`; extended `test_medication_library_files.py`.
- New `frontend/src/components/ReminderMonitor.test.tsx`; extended `MedicationEvidence.test.tsx` and `frontend/e2e/medication-gallery-refactor.spec.ts`.
- New `scripts/qa/inspect_library_release.py`, `check_supabase_test_target.py`, `medication_counts_in_browser.js` and this report; appended existing `docs/REQUIREMENTS.md` / `docs/DEFERRED_WORK.md`.

Verification recorded from actual terminal results:

| Command / suite | Result | Evidence category |
|---|---|---|
| `THREADS_TEST_DSN=postgresql://postgres@127.0.0.1:55441/postgres python -m pytest tests/backend/test_library_lifecycle_sql.py -q` |26 passed | Real PostgreSQL17.11; platform shims |
| Focused backend suite: compatibility, PDFs, target guard, evidence, Supabase data, history adapter/API, enrollment, reminders/delivery, long-term care and Render deployment |230 passed in the final focused run (includes effective health flags) | Local/mock. Not live Supabase |
| Five affected frontend files: MedicationEvidence, MedicationLibraryFileManagement, ReminderMonitor, RegimenHistoryScreen, PatientNavigation |49 passed | Components, mock APIs |
| Gallery/history Chromium suites |9 passed; added PDF-original browser journey1 passed separately | Browser, mocked Auth/HTTP; no real Storage |
| `npm test` full frontend |302 passed,2 failed,1 uncaught error across55 files | FAIL; unrelated shared-worktree test gaps below |
| TypeScript, ESLint, Vite build |PASS ? final recheck including additive health fields | Build keeps existing >500kB chunk advisory |
| Scoped Ruff, format, Git whitespace check |PASS; final checks recorded in acceptance ledger | Local static checks |
| Real authenticated Supabase Auth/Storage; physical device; production lifecycle writes |BLOCKED / NOT RUN | No isolated project; production not used as a substitute |

Full frontend failures were preserved: `App.test.tsx`'s account-metadata test lacks the new `api.doseFollowUps` mock, producing an uncaught TypeError; `RecordSemantics.test.tsx` expects the old Care Tasks empty/form copy. This task did not rewrite those tests or the other conversation's Today/Care Task implementation. The first added PDF HTTP test also had an incorrect test Content-Type on its JSON PATCH; that harness header was corrected and its full lifecycle now passes. A component fixture was updated to explicitly enable031 when expecting Photo management. No assertion was weakened to manufacture success.

Read-only metadata/config snapshots remain ignored under `outputs/incident031/`. No secrets, patient rows or authenticated image links were copied into this report. Git index remained empty; no stage/commit/push/merge/deployment occurred. Suggested later isolated commit scope: `fix(api): keep pending medication file and dose-report capabilities gated by schema readiness`; exclude unrelated staged/working changes and get current owner approval first.

## Integrated RC supplement — 2026-10-19

Latest cross-feature evidence and source/deployment gates: [INTEGRATED_RELEASE_CANDIDATE](INTEGRATED_RELEASE_CANDIDATE.md). This supplements earlier counts, not a silent replacement of their evidence. All three independent switches (including ENABLE_CARE_TASK_FOLLOWUPS) must remainfalse for schema030. Real schema001–030 API/RLS/worker integration, independent032 SQL and mock compatibility checks:19 passed;031 realSQL26 passed;032/033 realSQL15 passed. Full frontend309 passed;16 distinct Chrome flows passed (17 executions including a repeat). Full backend1112 passed/1 failed/119 skipped: nine stale citation/presentation failures were resolved by public-contract assertions, but the ScenarioA RESTORE pronoun knowledge-read failure remains and is not waived. Real Supabase Auth/Storage is stillBLOCKED.

Read-only production catalog refreshed2026-10-19T11:05:46Z:027–030 applied/hash-match;031–033 absent. Public Render/Vercel health200 does not verify authenticated patient outcomes or deployed SHAs. Source isolation/active release identity and the remaining regression retain productionNO-GO for A;031–033 retain separateNO-GO gates. Newly confirmed tooling restriction: chronological --only refuses032/033 while031 is pending, even though their SQL does not depend on031. Do not deploy031 merely to satisfy the runner, modify its ledger or claim independent deployment is ready. No production/Git write or deployment occurred.
