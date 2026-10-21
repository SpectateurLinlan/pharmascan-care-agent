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

For Supabase setup, apply additive migrations in order with `python scripts/db.py status`, review the target and pending SQL, then `python scripts/db.py migrate` and `python scripts/db.py verify`. Do not reset an existing database. Rollback scripts intentionally refuse destructive loss of feature data. See the [deployment layout](../deploy/README.md) and [Render configuration](RENDER_DEPLOYMENT.md).

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

The native enrollment/history journey in `frontend/e2e/medithread-rc.spec.ts`
requires an isolated demo-mode API and Vite instance. Set `RUN_MEDITHREAD_RC=1`
and `QA_BASE_URL` to that frontend. Its second test expects a separate local
Scenario D server/frontend at `http://127.0.0.1:5178`. Build the synthetic timeline
through the public test factory (never use this factory as a deployment entrypoint):

```powershell
$env:PYTHONPATH='backend'
$env:RUN_RELEASE_BROWSER='1'
python -m uvicorn tests.backend.test_release_scenarios:create_review_test_app --factory --host 127.0.0.1 --port 8027
```

For that second frontend, set `VITE_API_TARGET=http://127.0.0.1:8027`, keep
both Supabase browser Auth variables explicitly empty, and start Vite on 5178.
Do not let a developer `.env.local` silently connect the isolated demo to real
Auth. The existing `release-review.spec.ts` also runs against this frontend with
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
