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

## Assistant 配置与实际可用状态

以下配置都在后端设置，不使用 `VITE_` 前缀。模板默认关闭；不要用开关替代数据库验收。

| 配置 | 作用与前提 |
| --- | --- |
| `ASSISTANT_KNOWLEDGE_V2_ENABLED` | 使用有来源和覆盖范围的药物标签证据，可独立于工作流启用。模型推理仍取决于原有 Gemini 配置，开关不能证明调用成功。 |
| `ASSISTANT_WORKFLOWS_ENABLED` | 请求使用持久化多步骤办理。需要完整候选 SQL、受限核验连接、原生照片/PDF 兼容验收及正式发布记录。 |
| `ASSISTANT_NATIVE_MEDIA_ENABLED` | 配套原图/PDF 保存、引用和清理核验。原生文件桥接可独立于 Assistant 开启，但仍须通过同一发布核验；不能只开启开关就保存文件。 |
| `ASSISTANT_PROGRESS_ENABLED` | 工作流执行进度。仅在工作流真正可用后生效，不会创建 worker 或发送通知。 |
| `ASSISTANT_EVIDENCE_DSN` | 专用 `assistant_evidence_login` 受限连接，仅从进程环境读取，不读 dotenv，不回退到管理员连接。连接/TLS/权限需独立准备。 |

`GET /api/health` 返回配置开关、实际应用源码哈希及 `assistant_runtime_status=not_checked`。
这是无外部探测的启动诊断，不能证明 Gemini 推理、数据库验收或办理成功。
`GET /api/agent/workflows/capabilities` 需要认证，返回本次请求的 `admission.available/reason`。
患者连接与受限连接必须读到同一发布记录，且记录必须匹配实际运行源码和数据库元数据。
主页普通读取不等待这项核验；办理请求检查失败时拒绝保存，普通问答保留现有降级行为。

常见原因：`feature_disabled` 为开关或候选未装配；`verification_unavailable` 为受限连接未就绪；
`release_not_accepted` 为未发布或数据库结构/权限发生变化；`application_mismatch` 为应用版本不符；
`release_target_mismatch` 为两条连接的发布目标不一致；`native_media_not_ready` 为原生文件配套尚未准备；
`readiness_unavailable` 为核验读取失败。对外响应不包含连接串或原始数据库错误。

每次后端源码变更后都要重新确认发布记录。Windows 与部署平台的文件字节可能不同，
不得把本地哈希直接当作线上哈希；发布记录应绑定实际运行构建。
数据库候选及恢复限制见 [Assistant persistence candidates](../supabase/review/assistant_workflows/README.md)。
