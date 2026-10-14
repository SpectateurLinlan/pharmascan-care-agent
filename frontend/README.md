# PharmaScan Care — Patient UI

React/TypeScript/Vite patient app, designed primarily for 390–430px mobile portrait with desktop support. The [project README](../README.md) is the current entry point for introduction, setup, architecture, capability status and release gates.

## Start

With the current FastAPI backend running on port 8001:

```powershell
cd frontend
npm ci     # First install or lockfile changes only
npm run dev
```

Open the URL Vite prints (normally localhost:5173). The dev server proxies `/api` to `http://127.0.0.1:8001`; `VITE_API_TARGET` sets the development proxy target.

See [complete setup](../README.md#local-setup-and-startup) for Python and runtime profiles. Frontend login uses `VITE_SUPABASE_URL` / `VITE_SUPABASE_PUBLISHABLE_KEY`; server credentials stay in the backend environment. Business data and Stage2 operations use typed FastAPI APIs.

## Patient destinations

- **Today:** reviewed medication/dose/course information, current dose actions, reminders, visual Check and compact composer.
- **Medicines:** grouped current/upcoming/history/drafts; choose label or manual registration before the specific form.
- **Assistant:** contextual Gemini/tool path when configured, deterministic fallback when unavailable, six bounded recent turns.
- **History:** independently confirmed patient reports, optional health notes and real-data week/month/course summaries.
- **Me:** profile, account, reminders, language/speech, accessibility, privacy, About and feedback through separate pages.

Self-report uses a B14 challenge and independent confirmation sheet. Confirm writes one retry-safe event; cancellation leaves records unchanged. Failed record reads offer a retry action.

## Voice and preferences

One persisted en/zh preference controls UI, Browser SpeechRecognition `en-SG`/`zh-CN` and Agent output. Patients review/edit their transcript and press Send to continue.

Default playback is frontend **Browser SpeechSynthesis**, using available language-qualified voices with delayed `voiceschanged` loading. Play/Stop/replay/autoplay and a default 0.9x rate are supported. Missing/failed voices preserve text; no automatic Tencent fallback.

Optional Cloud TTS requires explicit session-only selection in Settings plus backend permission. Reload restores Browser. Browser STT/TTS may use remote services and are not guaranteed offline. Details: [voice providers and cost](../README.md#voice-providers-and-cost).

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

Personal gallery private persistence and eligible loose-pill matching are implemented and real-browser verified with synthetic inputs. Packaging/blister automatic matching, PDF extraction and caregiver management remain unavailable/partial. See the root README and current workflows for Demo A/B/C. Device voice/audio, medicine pronunciation, mobile keyboard and email-account flows need manual acceptance. Reminders operate while the app is active or reopened; patient data uses online APIs. Singpass is a future integration.

See [verification](../README.md#verification) and [acceptance checklist](../README.md#limitations-and-acceptance) for recorded checks and remaining work.
