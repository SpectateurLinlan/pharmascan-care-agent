# Offline Assistant evaluation

From the repository/worktree root, use the development Python environment:

```powershell
python scripts/qa/eval_assistant.py --mode offline --output outputs/assistant-acceptance/offline.json
```

The CLI runs only marked synthetic scenarios against injected memory services
and public-label replay. It does not load `.env`, invoke an LLM, connect to a
database, send notifications or use real Auth/device/provider services. Network
transports are denied; only in-process TestClient and explicit replay transports
are used. There is no live mode in this CLI. Output must resolve beneath this
worktree's ignored `outputs/assistant-acceptance/` directory.

The versioned suite is `tests/fixtures/assistant/acceptance_cases.json`. It covers
all 91 capability preparations and selected bilingual enrollment, knowledge,
consent, failure recovery and native write/readback journeys. Each case declares
its own phase and literal expectations. Preparation success does not establish
completed business work. Native completion requires actual owned readback and
receipt evidence; provider-only scenarios remain `not_run` offline.

The report contains safe per-case grades, required versus observed environments,
phase coverage, explicit failures/degradation/unavailability, and actual code,
design, case and fixture digests. It omits original turns, observations, patient
records, images and credentials. Offline model identities and unknown usage are
null; zero model requests means none were made. Case latency includes synthetic
fixture setup and execution; it is not a homepage/provider performance claim.

Exit codes:

- `0`: all requested objectives and phases passed.
- `1`: a failed objective, forbidden effect, missing case/capability, invalid
  configuration or artifact write failure blocks the result.
- `2`: the report is partial, with explicit unrun, unavailable, degraded or
  uncovered phases. This must not be described as full application acceptance.

P06's previously accepted native/browser evidence is not imported as a fresh
observation. The report compares current phase evidence with the full P06 index,
so remaining native/device phases are visible even when every preparation runs.
No aggregate safety percentage can hide an individual security failure.

For a deterministic comparison, run again with another private JSON filename.
Compare grades and coverage while excluding measured latency and generation
time. Actual external acceptance, budgets and deployment require their separate
approved workflow.

## Bounded P07 acceptance runner

The separate `run_assistant_acceptance.py` runner has modes `offline`,
`provider-memory` and `isolated-integration`. It defaults to offline with **zero
budgets**: all six cases are reported NOT RUN before a runtime or provider is
constructed. The older T1 CLI above remains offline-only and unchanged.

To exercise the new runner locally without external calls:

```powershell
python scripts/qa/run_assistant_acceptance.py --mode offline --max-cases 6 --max-seconds 120 --output outputs/assistant-acceptance/guarded-offline.json
```

This executes only the new runner's six categories, using existing synthetic
service fixtures: tool selection, Chinese manual collection, typo confirmation,
failed source/original retention, injected provider failure and independent
native observation confirmation/readback. It does not repeat the full T1/P06
suite. Real tool selection stays NOT RUN offline; local application checks,
label replay and injected errors are identified by evidence layer. Source and
provider failures may yield an expected `degraded` result and exit2/PARTIAL.
No result claims all capabilities, all native confirmations or provider coverage.

Live calls require separate owner approval of target/model/key/budget. **Do not
run the following template before that approval:**

```powershell
python scripts/qa/run_assistant_acceptance.py --mode provider-memory --allow-provider --model <approved-model> --api-key-env MEDITHREAD_ACCEPTANCE_GEMINI_KEY --max-cases 6 --max-requests 12 --max-seconds 120 --output outputs/assistant-acceptance/approved-provider-memory.json
```

Provide the key through the separately named acceptance environment variable;
never pass its value on the command line or save it in an artifact. The runner
does not load `.env`, Settings, the production key variable or database/Auth
configuration. The first supported bounded round allows at most6cases,
12wire attempts and120seconds; all must be explicit. Case limits and deadlines
span the suite, with existing four-model/four-tool per-turn limits retained.
Each SDK retry consumes a wire slot; redirects, foreign origins, ambient proxy
settings, Vertex routing and requests over64KiB cannot bypass the transport
guard. Native timeouts are capped by the remaining deadline. Synchronous I/O
stops cooperatively; an in-flight request may finish before the stop is observed.
These limits do not establish a currency cap or free-tier eligibility.

Reports distinguish actual external requests (`real_requests`), SDK transport
attempts including replay (`wire_attempts`), logical model invocations
(`model_requests`, including the marked injected-failure invocation), and actual
chat POSTs (`user_turns`). UI confirmation/upload requests are not chat turns.
Only a completed provider reply backed by actual external transport can count
as `model_success`. SDK replay never does. Actual nullable usage is preserved,
including usage returned after the answer deadline, and `usage_responses` gives
its coverage. A bounded partial case retains its spent attempts; unstarted cases
each retain an explicit NOT RUN result. Errors omit raw bodies and credentials.

Provenance includes a conservative explicit manifest of backend test/QA Python
helpers, shared graders/executors, controlled fixture files and packaged
application resources, plus the actual application source hash. Technical source
paths are listed in `provenance_files`; source/fixture contents are not copied into
reports. Valid actual SDK usage is retained on content/schema refusal as well as
deadline stops. These records describe consumed requests, not model success.

The four deterministic workflow/native fixtures retain `application_status` and
checks in provider-memory mode but their provider coverage remains NOT RUN.
The injected failure remains `fault_injection`, not a measured live outage.
Consequently this stage-scoped report can remain PARTIAL even if its one real
tool-selection case succeeds. Read evidence layers and missing coverage, not
only an overall status.

`isolated-integration` currently refuses execution before any external call.
The remote workflow composition and a verified isolated Auth/SQL/Storage profile
are not available under the current scope; a caller's isolation boolean or
production `.env` is insufficient. There is no silent memory fallback. Preparing
and approving such a profile, running real provider/persistence acceptance and
deployment remain separate tasks. The older `test_gemini_live.py` is a legacy
Auth/SQL suite and does not acquire these safeguards automatically.

Focused offline verification (explicitly excludes the live entry point):

```powershell
python -m pytest -q -p no:cacheprovider tests/backend/test_acceptance_runner_limits.py tests/backend/test_assistant_provider_acceptance.py -k "not test_live_provider_memory_acceptance"
```
