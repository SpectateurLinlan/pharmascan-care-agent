# MediThread development

## Acceptance and safety

For changes, state the expected outcome and choose checks proportionate to the affected component. Use a behavior matrix for substantial, clinical/data-sensitive or ambiguous changes; routine documentation/UI fixes can use a short acceptance note. Separate local mocks from database, provider, hosted and real-device evidence. Read [Safety and Evaluation](SAFETY_AND_EVALUATION.md) before making medication-safety or clinical claims; tests and code presence alone do not establish clinical validation.

## Local setup and startup

Prerequisites: Python 3.11+, Node.js 22.12+ and npm. From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,push]"
Copy-Item .env.example .env
Copy-Item frontend/.env.example frontend/.env.local
npm --prefix frontend ci
python scripts/start_dev.py
```

On macOS/Linux activate with `source .venv/bin/activate` and use `cp` in place of `Copy-Item`. The launcher starts FastAPI on `127.0.0.1:8001` and Vite on `localhost:5173`; Ctrl+C stops its own child processes. It installs nothing.

The local API automatically restarts when Python files under `backend/app` change.
The launcher supervises these restarts directly, avoiding Windows Uvicorn console-signal
issues; only its own backend process is replaced. After a Python error stops the API,
fixing and saving the source triggers another attempt while Vite stays running.
Vite provides frontend hot updates separately. Use `python scripts/start_dev.py --no-reload`
to disable backend reload. Restart the launcher manually after changing environment
variables, dependencies or the launcher itself; existing running servers must be
restarted once to pick up this new default. This affects local development only,
not Render or Dispatcher startup. Unsaved in-memory backend state can reset when
the API restarts; persisted account records are not deleted by reload.

If a port is occupied, stop the intended server yourself or choose other ports:

```powershell
python scripts/start_dev.py --backend-port 8011 --frontend-port 5181
```

Local synthetic mode uses `PERSISTENCE=in_memory`, `AUTH_MODE=demo` and optional `ENABLE_DEMO_SEED=true`. Data is lost on backend restart; the browser client identifier is not authentication. Do not expose this profile publicly. An absent model key uses an explicitly identified deterministic fallback, not simulated model success.

## Configuration

Use [.env.example](../.env.example) and [frontend/.env.example](../frontend/.env.example). Keep all real values out of Git.

| Area | Configuration and behavior |
|---|---|
| Patient persistence | `PERSISTENCE=supabase`, `AUTH_MODE=supabase`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`; frontend uses only the corresponding public Auth configuration. Anonymous Auth must be enabled. |
| Schema administration | `DATABASE_URL` is migration/worker configuration. Review migrations before applying them. Runtime patient business reads/writes use verified same-user credentials. |
| Gemini | `GEMINI_API_KEY`, `GEMINI_MODEL`, `MODEL_PROVIDER`; template selects `gemini-3.5-flash-lite`. Daily quota is server-enforced. No browser API key. |
| Stage2 | `VISION_API_BASE_URL`, bounded timeout. API version does not establish embedding compatibility: model, space, preprocessing, dimension and calibration must also agree. |
| Voice | **Browser STT/TTS are current defaults.** Tencent is an optional explicitly selected, server-gated provider requiring credentials and approval; it is not an automatic paid fallback. Device speech availability varies. |
| Web Push | `ENABLE_WEB_PUSH`, VAPID public/private keys and subject; install the `push` extra. Worker-only `PUSH_DISPATCH_TOKEN` signs bounded HTTPS dispatches. Keep worker credentials separate from patient HTTP; hosted scheduling and real-device delivery require separate verification. |
| Conversation history | Opt-in, disabled by default; displays up to 200 text exchanges from the last 30 days. This is a visibility window, not timed physical deletion: Supabase removes older/excess archive rows on a later append; inactive accounts can retain older text. Explicit Clear removes saved chat and recent context text, preserving clinical records. Six recent exchanges are separate model context; clinical facts come from authorized records. |

For Supabase setup, apply additive migrations in order with `python scripts/operations/db.py status`, review the target and pending SQL, then `python scripts/operations/db.py migrate` and `python scripts/operations/db.py verify`. Do not reset an existing database. Rollback scripts intentionally refuse destructive loss of feature data. See the [deployment layout](../deploy/README.md) and [Render configuration](RENDER_DEPLOYMENT.md).

## Running and testing

Backend only: `python -m uvicorn app.transport.app_factory:create_app --factory --app-dir backend --host 127.0.0.1 --port 8001`.
Frontend only: `npm --prefix frontend run dev` (development proxy defaults to port8001; override with `VITE_API_TARGET`).

The following are available checks, not a mandatory all-stack sequence. Select affected tests and tooling; use the full suite for an explicitly scoped integration/release check.

```powershell
python -m pytest -q -p no:cacheprovider
python -m ruff check backend tests scripts
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
```

Browser tests use Playwright and isolated synthetic QA servers. Set `QA_BASE_URL` and `PLAYWRIGHT_CHROMIUM_EXECUTABLE` for the installed Chrome/Edge binary; `RUN_LOCAL_UX=1` enables local UI journeys. External live tests remain opt-in and may require credentials, quotas and explicit synthetic-data consent. Default skips do not imply those integrations were tested. Test modules explain their individual flags. Do not enable every provider test simply to remove skips.


## Deployment entrypoints

See [deployment layout](../deploy/README.md) and [patient API on Render](RENDER_DEPLOYMENT.md). Do not deploy demo authentication or share Dispatcher secrets with the patient API.

## Isolated release browser checks

Current local navigation/calendar checks are in `frontend/e2e/experience/localNavigation.spec.ts`
with `RUN_LOCAL_UX=1`. Assistant enrollment and saved-conversation cases live under `frontend/e2e/assistant/`.
The old RC suite has been retired because its tour/form assumptions are superseded.
The independently gated five-day review journey is `frontend/e2e/records/releaseReview.spec.ts`;
it requires the synthetic Scenario D runtime below. This is a manual acceptance profile,
not evidence that the real database/provider or every selector has been revalidated in this refactor.
Build the timeline through the public test factory (never use it as a deployment entrypoint):

```powershell
$env:PYTHONPATH='backend'
$env:RUN_RELEASE_BROWSER='1'
python -m uvicorn tests.backend.test_release_scenarios:create_review_test_app --factory --host 127.0.0.1 --port 8027
```

For that second frontend, set `VITE_API_TARGET=http://127.0.0.1:8027`, keep
both Supabase browser Auth variables explicitly empty, and start Vite on 5178.
Do not let a developer `.env.local` silently connect the isolated demo to real
Auth. The existing `releaseReview.spec.ts` also runs against this frontend with
`RUN_RELEASE_BROWSER=1` and `QA_BASE_URL=http://127.0.0.1:5178`.


## Product Behaviour & Data Notes

| Area | Operating conditions |
| --- | --- |
| **Personal dosing** | Reviewed instructions only. Strength alone never determines pill count; unsupported conversions abstain. |
| **Overlapping plans** | Same normalised medicine name or known product ID is conservatively blocked, including different doses and PRN/scheduled combinations. This is an MVP restriction, not a judgment that a prescription is medically wrong. |
| **Stock & trends** | Patient-confirmed counts and report-based estimates. Sampled trends do not establish medication causality. |
| **Enrollment** | Supported images or reviewed manual entry. PDF ingestion and transparent-blister identification remain unverified patient workflows. |
| **Calendar** | Manual, one-time import; no automatic synchronisation. |
| **Notifications** | Caregiver contacts/consent do not prove delivery. Hosted/device delivery requires separately scoped evidence; source configuration is not proof of receipt and this is not a native system alarm. |
| **Saved chats** | Opt-in viewing: up to 200 exchanges / last 30 days. Older/excess rows are purged on a later append, not a timer. Explicit Clear leaves clinical records separate. |
| **Product scope** | Medication management and treatment-related follow-up. General screening, vaccines, prescribing and automatic pharmacy ordering are outside this release. Native apps and broader authorised caregiver delivery remain future work. |


## Persistent workflow offline preparation

`ASSISTANT_NATIVE_MEDIA_ENABLED` defaults to false. It controls the task-independent native verified-storage bridge separately from `ASSISTANT_WORKFLOWS_ENABLED`; flags do not grant target authorization. The restricted evidence connection is lazy and must be configured by an approved operator procedure before accepted bridge use. Missing verification fails closed before external file writes.

Run `python scripts/qa/inspect_assistant_evidence_scope.py` for an offline source/role inventory. It performs no network calls and reports execution readiness as false. `run_assistant_acceptance.py --persistence-preflight --persistence-profile <private-json> --persistence-purpose sql_read` validates explicit admission only, preserves zero provider budget and exits 2 with `NOT_RUN`; it does not execute acceptance or load `.env`.

The live definitions in `test_persistent_workflow_sql_live.py` and `test_persistent_workflow_storage_live.py` remain skipped without explicit opt-in, exact target/hash approval and operation scope. Use the existing private execution runbook for the target-specific checklist; never place profiles, tokens, uploads or acceptance evidence in public source artifacts. Do not install proof hooks alone on an active legacy native application.

## Source ownership and dependency checks

Use the [source directory map](../frontend/src/README.md) and the nearest directory README before adding files.
Screens and form models belong to their business feature; components is for shared UI.
The application composition root injects preference persistence and retains lazy page loading.
Run `npm --prefix frontend run check:architecture` for static/lazy/type-only import resolution,
explicit public feature boundaries and module cycles. It uses the existing TypeScript dependency.

## Naming and readable source

Use PascalCase for React components, camelCase for TypeScript utilities/hooks/test basenames,
and snake_case for Python. Hooks that own behavior use a descriptive useName name.
Keep framework entry/config filenames and .spec.ts/.test.ts suffixes.
Group tests by responsibility and execution contract; use describe blocks for related cases,
and share fixture setup without making mock/provider or patient ownership boundaries implicit.

Frontend source, tests, configuration and styles use pinned Prettier with 2 spaces and a 100-column target:
`npm --prefix frontend run format` writes formatting; `npm --prefix frontend run format:check` checks it.
Source ESLint requires separate variable declarations and blank lines around functions/import groups.
Use short responsibility comments and explain non-obvious confirmation, ownership and failure handling;
avoid comments that restate each statement. Python scripts use the existing Ruff 120-column convention:
`python -m ruff format --check scripts`. Format checks do not execute operational scripts.

The existing frontend typecheck also compiles shared e2e/support TypeScript fixtures, so required API DTO fields cannot silently disappear from the common mock.
