# Blocking / uncertainty register

| ID | Issue | Owner | Safe action without user | Human action needed | Status |
|---|---|---|---|---|---|
| B01 | v0.8.0 frozen candidate and GET conformance verified; image POST runtime behavior still unverified; tools/ScanPill schema gaps | Stage2 API owner + App | schema fixtures and typed adapter tests; manual enrollment unaffected | Supply permitted synthetic/public image fixtures and POST response conditions; clarify schema gaps | PARTIALLY RESOLVED; POST LIVE BLOCKED |
| B02 | External Supabase project URL/auth keys not supplied | App/infrastructure owner | Write migrations and testable repositories, no live DB claims | Create free project, configure environment | open |
| B03 | LLM/ASR/TTS service keys not supplied | App/Agent owner | dependency-injected fake provider + deterministic agent tests | Supply keys through local secret manager | open |
| B04 | Main GitHub code and repository URL not inspected | App owner | inspect workspace when WorkBuddy starts | Verify correct local repo and git remote | open |
| B05 | Stage1 multi-pill detector unverified; single pill → duplicate boxes in `/scan` | Vision owner | guarded single-pill manual crop path + regression test | fix/demonstrate detector stability | open |
| B06 | Cover, social URL, demo video, final web URL missing | Submission owner | prepare slots, storyboard and checklist | create/upload externally | open |
| B07 | Exact submissions form marks for Architecture PPT and Demo optionality not independently verified | Submission owner | distinguish target from verified organiser requirement | inspect final submission portal | open |
| B08 | Stray reserved-name junk file `nul` (34 bytes) in repo root, created by an accidental `2>nul` redirect in Git Bash; agent tooling gets ACCESS_DENIED on delete/rename (likely open handle). Already `.gitignore`d, harmless to git ops | App owner | none (ignored by git) | from own terminal run: `del \\.\D:\Projects\pharmascan-care-agent\nul` | open |
| B09 | `npm install` does not fetch the platform-optional native binaries on this machine (`@rollup/rollup-win32-x64-msvc`, `@esbuild/win32-x64`). `vite build`/`vitest` fail with MODULE_NOT_FOUND until they are installed explicitly | App owner | already worked around: both were installed explicitly and are recorded in `frontend/package-lock.json`; build and tests pass | none, unless a clean `npm ci` on another machine reproduces it — then run `npm i @rollup/rollup-win32-x64-msvc @esbuild/win32-x64` | mitigated |
| B10 | No camera capture path and no live image pipeline in the UI. `[Check pill]` is deliberately disabled and labelled unavailable rather than faking a result | App/Vision owner | button rendered disabled with an explicit "unavailable" label and a "visual check not run" notice | requires the frozen Stage2 contract (B01) before a real capture+match flow can be built | open (by design) |
| B11 | Background dose reminders are not implementable locally. The in-tab Notification reminder (opt-in, permission-gated) is real, but delivery while the app/tab is CLOSED needs a service worker plus either a push subscription or a scheduled server job — neither exists in this build, and there is no deploy target yet | App/UI owner | shipped an honest in-tab reminder with an explicit on-screen limitation ("works only while this page is open"); permission is requested only on an explicit user gesture, never on load | decide whether background push is in scope; if yes, needs a service worker, a push provider and a deployed backend | open (by design) |

## B01 detail — v0.8.0 partially verified, live POST branch BLOCKED

Resolved this turn: stored owner-supplied v0.8.0; preserved real 0.4.0; audited all 17 operations/51 schemas; built typed adapter and 12 SCHEMA_FIXTURE cases; live GET /health and /v1/model-info both HTTP 200/application/json with zero schema errors (see outputs/stage2_live_smoke.json). No live mismatch observed for these GETs.

Blocked specific tasks: image POST live integration, authenticated patient label extraction/camera wiring, detector/performance claims.
Why human evidence is needed: no known permitted synthetic/public image test asset in this repository; schema cannot verify deployed inference. We do not upload real patient data or invent images/licences.
Exact human steps: (1) ask Vision owner to provide an explicitly permitted synthetic/public image plus licence/source and expected request parameters; (2) add it under tests/fixtures/stage2 with provenance, no PHI; (3) provide successful/error responses for embed/match/identify/scan/read-label, including status/content-type; (4) clarify /v1/tools 200 `{}` and typed ScanPill additions.
Resume at: docs/API_CONTRACTS.md section G, tests/backend/test_vision_adapter.py, tests/fixtures/stage2/capture_live_get.py (GET-only; do NOT repurpose for POST without upload-consent controls), backend/app/infrastructure/stage2_label_adapter.py and the next authenticated source HTTP route. Run `.venv-equivalent python -m pytest tests/backend/test_vision_adapter.py tests/backend/test_stage2_schema.py -q` using the managed default env.
Safe alternatives completed: SCHEMA_FIXTURE adapter mapping, input validation, missing/null/metadata failure tests, Fake provider labelled SIMULATED, manual enrollment unchanged. Continue independent app/database tasks; this does not block all work.

Contract gaps: /v1/tools lacks typed response; ScanPill only types box/quality/count/imprint fields and permits arbitrary additional match/catalogue fields. These are not silently inferred. Embedding schema does not itself enforce length=256: app additionally enforces it.

## B12 — Credential in tracked example config (BLOCKED security branch)

Specific task: submitting `.env.example` or using the newly observed database configuration.
Why human confirmation: a concurrent edit introduced apparent live database credentials into a tracked example file; no database use or authorization was requested here. This file is excluded from our local commit. Secret values are never copied into evidence/report/memory.
Exact human steps: rotate the database password in the provider console, move the real configuration to ignored `.env` or local Secret manager, restore `.env.example` to credential-free placeholders, verify that it was not committed/shared elsewhere. Never paste secrets into chat.
Resume at: review `.env.example` diff locally (do not publish it), then the authorized Supabase integration branch and secret-scan before any manual remote operation.
Safe alternative: complete Stage2 public GET/schema tests without database access. Other work continues. No secret has been used by this session.
Evidence-sharing correction: apparent credential text was exposed in an earlier raw diff tool output in this conversation. Treat the raw transcript/screenshots as potentially sensitive; redact that output before sharing and rotate the credential. Do not claim all raw conversation evidence was already scrubbed. Final deliverables do not contain credential values.

## B13 — PDF source transport remains BLOCKED / supported schema, not implemented upload

Task: live PDF `/v1/read-label` upload. Schema accepts PDF and source pdf_text/pdf_scan, but current HTTP implementation intentionally accepts decoded PNG/JPEG only.
Human/engineering step: authorize a synthetic PDF fixture, define size/page/sanitization limits, implement validated PDF upload at the existing transport boundary; do not build another OCR.
Resume: backend/app/infrastructure/stage2_http.py + tests/backend/test_vision_adapter.py. Meanwhile readable image source Port and manual fallback remain available.
