# PharmaScan Care — patient UI

Minimum patient-facing UI for the PharmaScan Care demo. Built for Gate 4 of
`prompts/02_OVERNIGHT_BUILD_CRAFT.md`.

## What this is

A portrait-first, large-text, single-patient interface that talks **only** to
our own FastAPI backend over HTTPS JSON. It never connects to PostgreSQL, the
Stage2 vision API, or any external service directly.

## What is real vs simulated

| Area | State | Why |
|---|---|---|
| Backend HTTP API | **real** | `backend/app/transport/` — 26 HTTP tests, verified E2E |
| Persistence | **simulated (in-memory)** | no PostgreSQL/Docker on this machine (B02) |
| Assistant replies | **degraded mode** | no LLM key; deterministic rule router (B03). Every reply is tagged `mode=deterministic_degraded` |
| Pill photo check | **not built** | no camera pipeline and no live Stage2 provider (B01). The button is disabled and labelled `unavailable` on purpose |

The UI shows these states to the patient rather than hiding them.

## Run it

```bash
# 1) backend (from the repository root)
python -c "import sys; sys.path.insert(0,'backend'); import uvicorn; \
from app.transport.app_factory import create_app; \
uvicorn.run(create_app(), host='127.0.0.1', port=8000)"

# 2) frontend
cd frontend
npm install
npm run dev            # http://localhost:5173
```

The dev server proxies `/api` to `http://127.0.0.1:8000`, so no CORS setup is
needed in development. Override with `VITE_API_TARGET` if the backend runs
elsewhere.

> **Note:** on some Windows setups `npm install` does not fetch the platform
> native binaries. If `vite build` fails with `MODULE_NOT_FOUND`, run:
> `npm i @rollup/rollup-win32-x64-msvc @esbuild/win32-x64` (see B09).

## Scripts

| Command | Purpose |
|---|---|
| `npm run dev` | dev server with API proxy |
| `npm run build` | type-check + production build |
| `npm run typecheck` | `tsc --noEmit` only |
| `npm run test` | vitest (API client contract tests) |

## Screens

- **Today** — the dose that is due, with `[Taken] [Not now] [Unsure]` and a
  disabled `[Check pill]`. History shows `not reported` distinctly from a
  missed dose.
- **Medications** — active list, plus the draft → review → confirm → activate
  flow. A draft is never active on its own; activation needs a reviewed source
  and an explicit, single-use confirmation.
- **Assistant** — text (and optional browser speech input). Every reply shows
  its `mode` tag so it cannot be mistaken for a live LLM.
- **Settings** — lists what is deliberately not built.

## Design constraints honoured

- portrait-first single column, landscape/tablet two-column at ≥640 px
- minimum 52 px touch targets, base font 19 px
- follows the system light/dark preference
- state is never conveyed by colour alone — every status has a text label
- no page claims a result the backend did not return
