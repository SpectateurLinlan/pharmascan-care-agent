# MediThread — Patient UI

React/TypeScript/Vite patient app, designed primarily for 390–430px mobile portrait with desktop support. The [project README](../README.md) is the current entry point for introduction, setup, architecture, capability status and release gates.

## Start

With the current FastAPI backend running on port 8001:

```powershell
cd frontend
npm ci     # First install or lockfile changes only
npm run dev
```

Open the URL Vite prints (normally localhost:5173). The dev server proxies `/api` to `http://127.0.0.1:8001`; `VITE_API_TARGET` sets the development proxy target.

See [complete setup](../docs/DEVELOPMENT.md#local-setup-and-startup) for Python and runtime profiles. Frontend login uses `VITE_SUPABASE_URL` / `VITE_SUPABASE_PUBLISHABLE_KEY`; server credentials stay in the backend environment. Business data and Stage2 operations use typed FastAPI APIs.

## Patient destinations

Each Today medicine keeps its name, reviewed dose, time, course and report/reminder status visible. View medication actions expands that medicine's photo comparison, self-report and snooze buttons. Compare a pill photo describes the camera/upload purpose; a photo does not establish safe-to-take status. Explicit dose confirmation remains separate.

Today uses one overview of all medicine names/doses/times and one selected detail. Only the selected detail reads dose status; no hidden slide polls. A reminder selects its referenced regimen. No automatic medication merge or change occurs.

Accessibility uses a numeric100–150% slider stored in patient_profiles.text_scale_percent through the normal preference API. Root font scaling and rem-based text apply to all labels, navigation, buttons and dialogs; measured header/nav heights protect the composer. Legacy Large maps to125%. Drag previews locally; release/key-up/blur commits once, and failed save restores the previous preference. Migration019 must be applied before numeric writes; restart backend after updating the typed preference DTO.

- **Today:** reviewed medication/dose/course information, current dose actions, reminders, visual Check and compact composer.
- **Medicines:** grouped current/upcoming/history/drafts; choose label or manual registration before the specific form.
- **Today > Assistant (in-place layer / legacy child link):** contextual Gemini/tool path when configured, deterministic fallback when unavailable, six bounded recent turns.
- **Records:** independently confirmed patient reports, optional health notes and real-data week/month/course summaries.
- **Me:** profile, account, reminders, language/speech, accessibility, privacy, About and feedback through separate pages.

Self-report uses a B14 challenge and independent confirmation sheet. Confirm writes one retry-safe event; cancellation leaves records unchanged. Failed record reads offer a retry action.

## First-use guide

After a successful first load, a seven-step non-dismissible tour explains the four tabs, photos, editable transcript/Send, B14 and actual speech defaults. User-scoped v2 browser storage preserves unfinished steps across blur/reload; only explicit Finish/Skip records a terminal status. Manual replay from Me > Help / User Guide retains the original result. Restricted browser storage can prevent persistence. Background controls are inert; Escape/outside clicks do not close the guide. Header personal/settings duplicates are removed; those functions live in Me.

## Voice and preferences

One persisted en/zh preference controls UI, Browser SpeechRecognition `en-SG`/`zh-CN` and Agent output. Patients review/edit their transcript and press Send to continue.

Default playback is frontend **Browser SpeechSynthesis**, using available language-qualified voices with delayed `voiceschanged` loading. Play/Stop/replay/autoplay and a default 0.9x rate are supported. Missing/failed voices preserve text; no automatic Tencent fallback.

Optional Cloud TTS requires explicit session-only selection in Settings plus backend permission. Reload restores Browser. Browser STT/TTS may use remote services and are not guaranteed offline. Details: [provider configuration](../docs/DEVELOPMENT.md#configuration).

## Commands

| Command | Purpose |
|---|---|
| `npm run dev` | Vite development server/API proxy |
| `npm run lint` | ESLint |
| `npm run typecheck` | TypeScript check |
| `npm run test` | Vitest local/synthetic regressions |
| `npm run build` | TypeScript build and production assets |
| `npm run test:browser` | Playwright scenarios; live journeys require explicit opt-in |

Browser TTS adapter check:

```powershell
npm run test:browser -- e2e/browser-tts.spec.ts
```

Start the frontend/backend, set `QA_BASE_URL` to the frontend origin and `PLAYWRIGHT_CHROMIUM_EXECUTABLE` to an installed Chrome/Edge executable. QA defaults to port 5174. Application journeys use `RUN_LIVE_BROWSER=1` and synthetic records; speech-event automation covers the browser wiring.

## Current limits

Personal gallery private persistence and eligible loose-pill matching are implemented and real-browser verified with synthetic inputs. Me → Caregiver contacts supports private add/edit/delete/reload through FastAPI and same-user RLS. Explicit storage permission is required; all contacts remain unverified with notifications and sharing disabled. Contact verification, caregiver account linking/delivery, packaging/blister automatic matching and PDF extraction remain unavailable/partial. See the root README and current workflows for Demo A/B/C. Device voice/audio, medicine pronunciation, mobile keyboard and email-account flows need manual acceptance. Reminders operate while the app is active or reopened; patient data uses online APIs. Singpass is a future integration.

See [testing](../docs/DEVELOPMENT.md#running-and-testing) and [current limitations](../README.md#8-scope--limitations) for verification scope and remaining work.

## Navigation and reminder QA

Four tabs: Today / Medicines / Records / Me. Assistant is a persistent Today-origin task view with light Medicines/Records entries. Guide progress is user-scoped browser storage, with explicit Skip/Finish and Me Help replay. Hash child routes preserve parent/origin behavior; missing medication context falls back to selection.

`RUN_LOCAL_UX=1 QA_BASE_URL=<isolated local URL> npx playwright test e2e/ux-navigation.spec.ts` exercises the actual UI + local in-memory FastAPI (not mocked HTTP and not live Supabase). Cloud-provider tests stay separately opt-in. `public/sw.js` handles private Web Push only and caches no patient data. The API exposes public VAPID configuration; private keys never enter Vite variables. [Worker, calendar and device acceptance](../docs/REMINDERS.md).

The local five-day review browser fixture is reproducible from public test files;
it requires no private screenshots, patient records or QA scripts. From the
repository root, with the development dependencies installed (PowerShell):

```powershell
$env:PYTHONPATH='backend'
$env:RUN_RELEASE_BROWSER='1'
python -m uvicorn tests.backend.test_release_scenarios:create_review_test_app --factory --host 127.0.0.1 --port 8025
```

In a second root terminal, use isolated test ports and empty Auth configuration:

```powershell
$env:VITE_SUPABASE_URL=' '
$env:VITE_SUPABASE_PUBLISHABLE_KEY=' '
$env:VITE_API_TARGET='http://127.0.0.1:8025'
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5195 --strictPort
```

In a third terminal under `frontend`, set `RUN_RELEASE_BROWSER=1`,
`QA_BASE_URL=http://127.0.0.1:5195` and an installed Chrome/Edge executable, then
run `npx playwright test e2e/release-review.spec.ts`. On Linux/macOS use `export`
for environment variables. This factory uses in-memory persistence and a virtual
clock; never expose it publicly or select it as the production application.
Stop the test servers after use. Image-provider demos instead generate their
synthetic inputs with `python scripts/generate_gallery_demo.py` (add
`--stage2-v010` for the upgraded sticker set), then explicitly opt in to live
calls. Generated `outputs/` are not source files to publish.

Photo result navigation has its own child route and retains the selected file on Back/Forward; late responses from a closed task do not reopen it. The local browser suite contains two real local-FastAPI journeys and one explicit visual-HTTP-MOCK navigation case. TypeScript tests use Node type declarations only for loading the committed service worker source; no Node filesystem code enters the application bundle.
## Medication care additions

Four tabs remain Today / Medicines / Records / Me. InventoryPanel belongs to medication detail; CareTasksScreen, AdherenceBarriersScreen and MedicationReviewScreen consume typed FastAPI endpoints. CareReviewSheet is shared by forms and Agent proposals and requires an explicit human Confirm before writes. HealthTrackingScreen reuses the observation API for validated numeric values. No stock/clinical calculation or database/Stage2 request was added to React.

Real browser E/F journey: `RUN_LONG_TERM_DEMO=1`; opt-in `RUN_GEMINI_CARE_DEMO=1` adds three bounded live turns. See [long-term care interfaces and acceptance](../docs/LONG_TERM_CARE.md). Default voice stays Browser SpeechRecognition/SpeechSynthesis, with no silent cloud call.
