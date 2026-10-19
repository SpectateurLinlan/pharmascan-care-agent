# Integrated release candidate verification — 2026-10-19

> **Latest 2026-10-19 owner scope and verification:** [Final local integration](LOCAL_INTEGRATION_VERIFICATION.md). Unified local commits supersede the earlier split-release plan below; production remains NO-GO. Earlier evidence is retained as history.


## Decision and evidence boundary

**Release A: schema030 compatibility PASS locally; production release NO-GO today.** Existing application paths can run without031–033. This is not approval to deploy the dirty worktree: an isolated release artifact/base has not been established and active hosted SHAs are unknown. The previously remaining Agent restore regression was resolved and the full backend suite is now green locally; details and scope are recorded in the follow-up below. No migration is needed to correct the reported local missing-object failures.

**Release B: production NO-GO for031,032 and033 individually.** SQL contract verification is available, but hosted Auth/PostgREST/Storage and coordinated release/recovery gates remain open. SQL dependency independence must not be confused with the chronological migration runner's prerequisites.

This report supplements, rather than erases, MEDICATION_LIBRARY_RELEASE_READINESS.md and the Today/Care status report. Initial frontend302/2 failures were already superseded by the other task's308 passes. This round subsequently obtained309 passes after adding a lifecycle visibility regression. Local tests never used production patient data as fixtures.

## Ownership and acceptance matrix

The UI owns presentation/navigation; FastAPI owns authenticated DTOs; application services own clinical/lifecycle decisions; request-scoped repositories own patient-token Data API access; the separate worker owns notification projection. This round changes no public HTTP DTO, database/RLS/Storage contract, medication activation rule, Stage2 model or worker schedule.

| Requirement | Owning boundary / direct verification | Result and scope |
|---|---|---|
| Existing application on schema030, all three new capabilities off | Actual persistent request factory → Supabase adapters → local SQL/RLS bridge; real001–030 only | PASS real PostgreSQL, synthetic Auth and bridged PostgREST wire; not hosted Supabase |
| Real medications, terminal regimen, evidence and an unreported occurrence remain visible | Public medication/regimen/gallery/history/Alerts responses, explicit record assertions | PASS same isolated test; not merely HTTP200/empty fixtures |
| Legacy task creation/isolation and worker deduplication | Public task RPC, A/B roles; queue synchronization twice, future claim rejected | PASS real PostgreSQL; no notification provider send |
| Active record does not disappear merely because planned end date passed | MedicinesHub/App shared predicate; component plus real Chrome Back/Forward/refresh | PASS local/mock; no patient lifecycle mutation |
| Browser library, detail/history and Today/Care regressions | Actual Chrome/React; mocked gallery APIs and synthetic local FastAPI Today server | PASS16 distinct journeys,17 executions including one repeated history journey |
| Full existing backend behavior | Full backend suite, including dialogue restore | PASS:1117 passed,120 opt-in skipped, synthetic/stub/local only; hosted Gemini and patient behavior NOT VERIFIED |
| Real Auth/Storage and hosted patient outcome | No verified isolated Supabase configuration or accessible authenticated owner context | BLOCKED / NOT VERIFIED; no substituted fixture counts |

## Incident and version reconciliation

The owner explicitly corrected the original environment to **localhost:5173**, not a Vercel incident. Local new code was using the real Supabase project with schema030. The original three missing-object dependencies were independently traced:

| Endpoint | Observed evidence | Confirmed local dependency / remediation |
|---|---|---|
| `/api/evidence/gallery` | Owner422/INVALID_INPUT, downstream404/PGRST205 | Unconditional031 PDF count read of `medication_library_files`; default-off031 service preserves legacy photo/source aggregation |
| `/api/reminders/alerts` | Same supplied error | Unconditional033 `effective_dose_events` reader; default-off033 selects existing `dose_events`; independent of031 |
| `/api/me/medication-history` | Owner-reported422; original body not retained | Unconditional033 `dose_report_entries` amendment read; now opt-in only |
| `/api/me/dose-follow-ups` | Owner identified503/PROVIDER_UNAVAILABLE, `Dose report follow-ups are unavailable` | New033 capability disabled; UI now explains unavailable and does not poll it or invent an empty result |
| `/api/me/medications` | No authenticated failing response retained | Core schema objects; isolated API returns the actual synthetic active record. Real patient count still NOT VERIFIED |
| `/api/me/regimens` / history-only UI | Reported smaller history count | Core API; UI folds successor versions, preserves distinct terminal chains. Newly fixed: active plans with a past planned end were excluded from Current without qualifying for History. This is not proof it explains every originally missing patient record |

Database missing table/column/function contracts now map to503/provider unavailable with scrubbed internal structured diagnostics, not patient422 validation. A physical missing table cannot be repaired by a schema-cache refresh. No cache reload was issued. Other input/business-rule422 responses remain distinct.

Fresh metadata observation: **2026-10-19T11:05:46Z**, explicit `transaction_read_only=on`, no patient-row queries. Custom `public.core_schema_migrations` contains001–030;027–030 normalized UTF-8 hashes match local files.031–033 remain absent. Supabase CLI migration ledger is absent. Evidence: ignored `outputs/integrated-rc/public-and-catalog.json`, `catalog.json` and `manifest.json`.

Fresh public observations at11:06Z: Render health200, OpenAPI200; Vercel proxied health200. Render exposes legacy Gallery/Alerts/history routes, without the new files/late-report routes or new capability health fields. These probes are not authenticated business acceptance. GitHub main status identifies `d6d9874cf807fadb220255aeff5d1bd2c3792ebd` with successful Vercel statuses dated2026-10-18; that does not establish the active Render or Vercel alias SHA. Local HEAD is `60ae19ab1553bda99e614fcace8c3a72db175222`, branch `feat/agentic-ux-landscape`. Do not deploy a speculative remote incident fix based only on local failures.

## Cross-feature review and changes in this round

The independent switches are all defaultfalse and must all remainfalse for A:

```dotenv
ENABLE_MEDICATION_LIBRARY_FILES=false
ENABLE_CARE_TASK_FOLLOWUPS=false
ENABLE_LATE_DOSE_REPORTS=false
```

They select031 file management,032 task follow-ups,033 effective reports respectively. Supabase request composition gates new services; history skips amendments; Supabase and native PostgreSQL event readers select the old table; worker task SQL projects the legacy reminder lead0 without requesting032 columns. Existing photo registration/private retrieval/comparison retirement, original reports, care tasks and Alerts remain supported. Advanced task fields are rejected before the legacy RPC can silently discard them. Calendar remains a future read-only DTO/documentation boundary; no Calendar write path was added.

Confirmed regression fixed here: `isPastCourse` previously inferred retirement from `course_end_date`. Because `/api/me/medications` returns active plans and History accepts explicit ended/superseded chains, such records could disappear from both. The shared predicate now uses explicit terminal state only; real course-start dates still separate upcoming plans. No backend dates/states are changed and no treatment recommendation is inferred.

The full backend run initially showed10 Agent conversation failures. Nine affected scenarios passed after correcting stale test expectations: current presentation retains clinical qualifiers with a changed introductory subject and supplies citation metadata in public `tool_traces`, rendered by the already-tested AnswerSources UI. New negative assertions verify that removing population qualifiers or public citations still fails. No Agent runtime code was changed.

**Resolved locally, 2026-10-19 follow-up:** `test_correctness02_dialogue.py::test_continuous_long_conversation[Scenario A...]`, turn17, now performs the expected grounded knowledge read after **RESTORE**. RESTORE intentionally restores bounded text without trusted medication IDs. Historical context selection matched the AMLODIPINE ingredient against both current strengths and treated the explicit Amlodipine10mg mention as ambiguous. It now resolves restored turns against the freshly listed current products, applies the strength filter, and carries forward only a unique match; a multi-product historical match stops recovery and still asks the patient to choose. The direct test verifies the exact current 10mg medication ID is read, and a companion test verifies ingredient-only Amlodipine context still prompts for a choice. No source-grounding, identity, schema, API or migration contract was weakened or changed. This local deterministic synthetic/stub evidence does not establish real Gemini or hosted behavior.

## Release B readiness and migration tooling

| Capability | SQL / local behavior | Independent enabling conditions | Production |
|---|---|---|---|
|031 PDF/photo lifecycle |26 real PostgreSQL cases PASS; mock HTTP/browser lifecycle PASS | Isolated real Auth/Storage; retention boundary; upload/registration reconciliation; safe cleanup/restore and file-security decision; approved exact artifact | NO-GO |
|032 care task follow-up UX | Part of15 real PostgreSQL cases PASS; full frontend and real Chrome/synthetic API PASS | Hosted RPC/RLS/worker compatibility, migration/recovery approval, task snapshot/reminder semantics, coordinated deployment | NO-GO |
|033 late-dose reports | Part of15 real PostgreSQL cases PASS, including030→033 without031/032; synthetic API/browser PASS | Hosted patient confirmation/RLS/concurrency/audit; all consumers and worker use effective reports; recovery preserves corrections; migration approval | NO-GO |
| Notification delivery | Existing31 reminder regressions included in full suite | Real provider delivery/duplicate/Snooze/device acceptance | NOT VERIFIED |

031 direct dependencies include001/003/015/018/029.032 upgrades the existing medication care-task table/RPCs, adding reminder lead and historical-entry metadata; it needs neither031 file tables nor033 reports.033 depends on core regimen/occurrence/confirmation/audit contracts, not031/032.032 reuses existing owner RLS/grants and queue;033 adds append-only owner-selected `dose_report_entries`, security-invoker `effective_dose_events`, a confirmed report RPC and original-event duplication guard.031 retains the separate evidence/embedding lifecycle. Current hashes are recorded in `outputs/integrated-rc/manifest.json`; none of these files was modified in this round.

**Runner constraint discovered in this round:** `python scripts/db.py migrate --only VERSION` verifies every earlier discovered filename/hash. With031 pending, it refuses032; with031/032 pending, it refuses033. Two focused tests execute that refusal branch and prove no migration/ledger write is called. An additional real PostgreSQL test applies032 directly on030 with031/033 physically absent, creates a task with30-minute reminder/history and verifies cross-owner isolation, then rolls the disposable transaction back. This confirms SQL independence, not production runner permission. Before independent032/033 rollout, prepare/review a bounded dependency-aware runner/operator procedure, including exact prerequisite hashes and ledger recording. This remains a tooling gate, not an approved new production operation.

Do not run unscoped `supabase db push` or `scripts/db.py migrate`: the custom ledger differs from the CLI ledger, and unrelated pending migrations could be included. The scoped runner also commits file DDL before recording its ledger, leaving a failure window. Any later approved execution must stop on ambiguity, inspect actual objects and ledger read-only, and obtain a precise recovery decision rather than blindly retrying.

Rollback boundaries:031 refuses nonempty file/audit tables;032 refuses new task semantics/history;033 refuses any report ledger entries. Existing evidence/corrections require forward repair. Once033 reports exist, disabling its effective reader or restoring a raw-event backend would hide patient corrections. Once032 metadata is used, an old worker must not ignore lead times/history. Storage bytes need their own recovery plan; the earlier pre030 database archive is not a fresh release backup or a Storage backup.

## Storage and file safety gates

No verified isolated Supabase project/config was found. `.env.supabase-test`, `.env.test`, `.env.staging` and frontend equivalents were absent. Offline target checker returnedBLOCKED without a connection. No real Auth/Storage result is claimed.

Existing production metadata only: private medication-sources bucket; no configured bucket MIME/size limits; owner-rooted object policies. Direct owner Storage operations do not enforce protected-source/tombstone rules. Application validation covers MIME/extension/signature/size and final PDF EOF, with private no-store/nosniff/sandbox response headers. It is not complete PDF parsing, malware scanning or an upload quota. PDF OCR/enrollment remains future functionality, verified in About EN/ZH by the browser suite.

Storage-write→DB-registration uncertainty is not solved by an indiscriminate cleanup: deterministic IDs and duplicate/tombstone preflight exist; ambiguous registration does not blindly delete possibly registered bytes. Durable reservations/orphan reconciliation, deletion failure recovery, shared-source protection through every access path and backup/restore testing remain031 release gates. No production files were accessed for testing or deleted.

An independent test project is necessary to close real infrastructure gates in this environment (a complete isolated local Supabase stack is an alternative if Docker becomes available):

1. Owner creates a clearly named test project in a **Free-plan organization**, if allowance permits; no production clone or paid provisioning. Official [billing FAQ](https://supabase.com/docs/guides/platform/billing-faq) allows two active Free projects; [plan billing](https://supabase.com/docs/guides/platform/billing-on-supabase) is organization-based. Account allowance must be checked in Dashboard.
2. Put only test configuration in Git-ignored `.env.supabase-test`: APP_ENV=test, AUTH_MODE=supabase, PERSISTENCE=supabase, TEST_PROJECT_REF, test URL/publishable key and a separate test DB credential. Keep patient-runtime settings separate from administrative setup settings. Never send credentials in chat.
3. Supply only the local file path and explicit authorization for synthetic tests on that named project. Run `scripts/qa/check_supabase_test_target.py --env-file .env.supabase-test`; then the actual runner must independently verify target separation and JWT issuer before every write. The current checker alone is not a write barrier.
4. Codex can subsequently prepare an explicitly capped schema fixture, synthetic A/B identities/files and real upload/private preview/download/edit/delete/isolation/cleanup tests. Test031 and032/033 in independently reviewed configurations; do not auto-bootstrap every pending migration. No project was created or configured now.

## Release isolation and CI/CD

Render Blueprint uses `autoDeployTrigger: commit`; patient backend builds with `pip install .` and launches `scripts/run_patient_api.py`. Frontend Vercel builds from frontend with `npm ci --include=dev`, `npm run build`; `/api` rewrites to Render and non-API routes to the SPA. Worker is a separate deployment. Actual Dashboard branch bindings/root settings and active SHAs remain unverified. A push can trigger more than one project; do not treat push and deployment as independent harmless steps.

**Recommended A source isolation:** a new worktree/branch from the verified deployed baseline after authorization, applying reviewed compatibility hunks only. Candidate hunks are config/default-off health contracts, Supabase missing-object error mapping, request composition, legacy event/history/worker selectors, Gallery unavailable-versus-empty behavior, Today/Care capability handling, and the active-plan visibility correction with their focused tests. Shared App/client/container/DTO files also contain PDF, enrollment, History and Care changes: never select them wholesale just because one hunk belongs to A. Retain required public DTO default compatibility, not new feature activation.

Explicit exclusions for the minimal A patch:031–033 migration execution/activation; PDF management/upload/delete implementations and controls; unverified Storage changes; Calendar implementation; unrelated enrollment/Agent changes; diagram/README/catalog maintenance.031 and032/033 source dependencies in the current container mean copying the current container file alone is not a valid isolated patch. A must either remove those imports in the isolated baseline patch or explicitly include/review the complete dormant dependency closure. Current integrated-tree tests do not certify that not-yet-created artifact.

Prepared operations **only after exact Git approval**, not executed here:

```text
git worktree add -b release/schema030-compat <new-local-release-directory> <verified-deployed-baseline-SHA>
git -C <new-local-release-directory> apply --check <reviewed-A-only.patch>
git -C <new-local-release-directory> apply <reviewed-A-only.patch>
# Run the schema030/component/browser/build suite against that exact isolated artifact.
git -C <new-local-release-directory> diff --check
git -C <new-local-release-directory> add -- <explicit-approved-paths>
git -C <new-local-release-directory> diff --cached
git -C <new-local-release-directory> commit -m "fix(release): preserve schema030 medication and reminder compatibility"
# Push, branch binding, Render, Vercel and worker deployments each need their exact approved scope.
```

The placeholders are deliberately unresolved prerequisites, not invented release IDs. No branch, patch commit or deployable SHA is claimed. First obtain active Render/Vercel SHAs and branch bindings from Dashboard/read-only release metadata, and resolve/explicitly scope the remaining acceptance failure. Then review a concrete isolated diff and ask for the exact Git/push/deployment approvals; not now whileNO-GO.

## Hosted acceptance and recovery plan — NOT EXECUTED

For A, recheck ledger/flags read-only, then separately approve backend compatibility release before the matching frontend. Update worker only if its compatible artifact is separately reviewed/approved; keep its sending configuration unchanged. No DB/Storage change is required. Verify deployed immutable SHAs, public health and all three flagsfalse, then authenticated patient-scoped smoke:

- Current Medications200 and actual displayed list; Regimens200, real lifecycle distribution and terminal-chain History count; Gallery200 plus owned legacy images and correctly unavailable PDF management; Alerts200; medication-history and regimen-scoped dose-history200 with missing-versus-reported semantics.
- Today original reports and existing Care Tasks work; new follow-up requests are not fired while033 is off. Confirm error/loading/empty distinctions, modal dismissal, reminder duplication/Snooze expiry and no unintended writes on read/filter.
- Run Global Library→product→Detail→Back/Forward, History→Detail→Back/refresh, direct URLs, EN/ZH and mobile/desktop. An account with no data is not a substitute for an account containing the expected records.
- Use existing authenticated browser session and `scripts/qa/medication_counts_in_browser.js` for only statuses/item_count/state counts. Never export localStorage, headers, HAR with tokens, names/IDs or record contents. For other endpoints summarize status/count only locally. Real owner counts remainNOT VERIFIED in this task.

A recovery: stop rollout on failed smoke, restore the preceding verified API/frontend artifact and compatible flags, preserving every patient row. No automatic migration/ledger rollback or production test records. For B later, stage the individually approved migration/procedure and compatible backend/worker before enabling its matching capability; verify real Auth/RLS and synthetic hosted lifecycle/audit/cleanup checks on an authorized isolated environment first. On execution ambiguity stop, preserve diagnostics and use the reviewed forward-repair/recovery decision. Do not enable033 while any report consumer still reads raw events.

## Actual verification and repository record

| Command / evidence under `outputs/integrated-rc/` | Actual outcome |
|---|---|
| Full `pytest tests/backend -q`, follow-up 2026-10-19 |1117 passed,120 opt-in skipped; no failures. Run against current shared working tree; earlier historical results remain preserved in backend.txt |
| Focused Scenario A RESTORE + unique-product and ambiguity regressions |3 passed; exact medication read and ambiguity clarification checked through synthetic HTTP/application/tools |
| Relevant Agent tests: dialogue, boundaries, core, temporal/SQL and model agent |135 passed,25 opt-in skipped |
| `THREADS_TEST_DSN=localhost55441 pytest test_release_a_schema030.py test_library_release_compatibility.py -xq` |19 passed;2 real PostgreSQL cases (030 API/worker and independent032) plus17 mock/unit tests, including two runner refusal cases; latest schema030-final.txt |
| `THREADS_TEST_DSN=localhost55441 pytest test_library_lifecycle_sql.py` |26 passed in sql031-and030.txt (27 total there includes earlier version of030 test);031 unchanged since that run |
| `THREADS_TEST_DSN=localhost55439 pytest test_today_care_sql.py -q` |15 passed, actual PostgreSQL/RLS/RPC/concurrency/rollback, platform shims |
| Full `npm test -- --reporter=dot` after UI fix |309 passed /55 files, frontend-final.txt |
| Playwright gallery/history/Today/Care, then ended-plan specialty, then strengthened History |14 +1 +2 passed;16 distinct, one repeated; actual Chrome, mock Auth/APIs or synthetic memory FastAPI, no real Push/Storage |
| TypeScript, ESLint, Vite build |PASS; existing large chunk warning retained |
| `ruff check backend/app tests/backend`, touched Python format, `git diff --check` |PASS at final review; no broad formatting |
| Read-only schema/public metadata |PASS metadata only;027–030 applied/hash-match;031–033 absent; health200 not patient-outcome proof |
| Real Supabase Auth/Storage / physical devices / hosted authenticated acceptance |BLOCKED / NOT RUN / NOT VERIFIED respectively |

Harness corrections during the new030 test were verified against actual contracts: regimen_id is required for due/dose-history; image kind is `package`; history uses `scheduled:<id>`; worker claim returnsNone when empty; task source is `patient_reported`. These were fixture errors, not production API defects. Final test additionally proves an actual unreported occurrence appears in history and Alerts, reference-only packaging does not become eligible, and a real legacy task is queued once without early dispatch. No timeout/delay workaround was added. The final19 focused passes follow the full backend run; the additional two runner tests and standalone032 SQL test were not presented as a rerun of the entire suite.

Files changed **in this round**, not the whole dirty tree:

- `frontend/src/components/MedicinesHub.tsx`, `frontend/src/App.tsx`: shared terminal-state visibility predicate/callers.
- `frontend/src/components/PatientNavigation.test.tsx`, `frontend/e2e/medication-regimen-history.spec.ts`: active past-planned-end and navigation regressions.
- `tests/backend/test_release_a_schema030.py` (new): disposable schema030, real patient-role SQL through persistent API graph, actual records/worker, explicit local-only guard and cleanup.
- `backend/app/agent/read_dialogue.py`: restore contextual medication resolution through current exact product/strength matches; only a unique result resumes the read.
- `tests/backend/test_correctness02_dialogue.py`: align public presentation/citation assertions, add two negative protections, and add restored unique-product plus ambiguous-ingredient regressions.
- `tests/backend/test_library_release_compatibility.py`: two no-write chronological runner refusal tests.
- This report; additive entries in MEDICATION_LIBRARY_RELEASE_READINESS, REQUIREMENTS and DEFERRED_WORK.

All other dirty files, including Today/Care,031–033, enrollment, images, catalog and README changes, were preserved. Final worktree:150 changed/untracked paths (90 tracked modifications,60 untracked), zero staged paths; branch/HEAD unchanged. These are shared-tree totals, not this round's exclusive file count. No stage/commit/merge/reset/rebase/push/worktree creation, production migration/data/Storage/RLS/cache/Secret change or deployment was performed. Only test processes started by this round were stopped at exit (5193/8791 and the two known isolated PostgreSQL clusters); existing5173/8001 remain untouched.

Next responsible actions: (1) establish the actual deployed baseline/source bindings; (2) after explicit Git authorization isolate and retest A, then request precise deployment approval; (3) owner-provision an isolated Supabase configuration to close B's real infrastructure gates, and review migration runner/recovery prerequisites. Readiness or this plan grants none of these production/Git permissions.
