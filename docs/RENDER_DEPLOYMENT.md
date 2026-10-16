# Patient API on Render Free

Preparation only: no service, credentials, migration or deployment is created by
these files. Use the repository checkout, not an isolated backend wheel.

## Dashboard configuration

After owner approval, open [Render Dashboard](https://dashboard.render.com/),
New > Web Service, and select the reviewed repository/branch. Creating the service
can immediately start its first deployment: do not submit that form before release
approval. Alternatively import `deploy/render/render.yaml` after approval and set
the Blueprint Path to that path. The service Root Directory is still the repository
root, not the Blueprint folder. The Blueprint selects `free` and enables automatic
deploys on commits to the linked branch, as requested by the owner. Importing it
also starts the initial deployment; local file saves alone do not deploy anything.

| Field | Value |
| --- | --- |
| Runtime | Python |
| Root Directory | Leave blank (repository root) |
| Region | Singapore |
| Instance | Free (512 MB, 0.1 CPU) |
| Build Command | `python -m pip install . && python scripts/run_patient_api.py --check-resources` |
| Start Command | `python scripts/run_patient_api.py` |
| Health Check Path | `/api/health` |
| Auto Deploy | On Commit (`autoDeployTrigger: commit`) |
| Python | Existing root `.python-version`: `3.12`; Render selects its latest patch |

Do not add a migration/pre-deploy/seed command. Existing Supabase is reused;
no Render database, disk, cron or background worker is provisioned.

## Environment variables

Enter configuration in this service only; do not attach the Dispatcher's shared
environment group or upload a local `.env`. The launcher explicitly reads process
environment, validates it and passes Settings to the existing application factory.

| Name | Value / purpose | Classification |
| --- | --- | --- |
| `APP_ENV` | `production` | Nonsecret |
| `AUTH_MODE` | `supabase` | Nonsecret, required |
| `PERSISTENCE` | `supabase` | Nonsecret, required |
| `ENABLE_DEMO_SEED` | `false` | Nonsecret, required |
| `APP_ORIGIN` | Actual Vercel frontend HTTPS origin, without path or trailing slash | Nonsecret |
| `SUPABASE_URL` | Existing project's HTTPS URL | Public project configuration |
| `SUPABASE_PUBLISHABLE_KEY` | Existing publishable/legacy anon key; never service role | Public project configuration |
| `MODEL_PROVIDER` | `gemini`; `deterministic` only for explicitly degraded testing | Nonsecret |
| `GEMINI_API_KEY` | Existing approved provider credential | Server-only Secret |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` (current code default) | Nonsecret |
| `GEMINI_THINKING_LEVEL` | `low` | Nonsecret |
| `DEMO_AGENT_DAILY_TURN_LIMIT` | `20` | Nonsecret |
| `VISION_API_BASE_URL` | `https://davidpansx-pharmascan-api.hf.space` (current endpoint) | Public provider URL |
| `ENABLE_WEB_PUSH` | `false` for this first patient deployment | Nonsecret |
| `ENABLE_SPEECH` | `false` | Nonsecret |
| `STT_PROVIDER`, `TTS_PROVIDER` | `browser` | Nonsecret |
| `PORT` | Supplied by Render; launcher defaults to `10000` locally | Platform configuration |

Never configure `DATABASE_URL`, `SUPABASE_SECRET_KEY`, service-role keys,
`PUSH_DISPATCH_TOKEN`, `VAPID_PRIVATE_KEY` or Tencent cloud speech credentials on
this initial patient service. The launcher rejects the first four applicable
Settings credentials and refuses Web Push/cloud speech enablement for this phase.
Future patient subscription/test functionality needs its own reviewed configuration
step; toggling a flag here does not establish Push delivery readiness.

## Process and resource isolation

* Patient process: this launcher -> `app.transport.app_factory.create_app` ->
  same-user JWT Supabase Data API. One Uvicorn worker, no reminder subprocess.
* Independent Vercel Push project: `deploy/dispatcher/index.py`, selected by root
  `pyproject.toml` and `vercel.json`, -> existing worker;
  worker DB/HMAC/VAPID credentials stay there. Its `.vercelignore` deliberately
  excludes `docs/` and must not be reused as the patient package manifest.
* Static Vercel frontend: root `frontend`, public Auth variables only. Configure
  an HTTPS external `/api/:path*` rewrite to the actual Render host after approval.
  Never cache patient responses; verify uploads and Authorization survive the proxy.

The adapters load `docs/external/pharmascan-api-openapi-0.10.0.json` relative to
`backend/app/`. The build check parses the retained contract and imports runtime
dependencies without contacting providers. Keep `backend/`, `scripts/`,
`pyproject.toml`, `.python-version` and this public JSON file in the release.
Dependency ranges are not a lockfile: preserve the first successful build's Python
patch/dependency versions for reproducibility. Windows import/build checks do not
prove Linux wheels, installed size or Render build success.

## Free resource and timeout risks

Gemini and Stage2 inference run remotely, but JSON processing, image decoding and
PNG re-encoding consume this service's CPU/RAM. A 16-megapixel RGB buffer is about
48 MB; several copies, request/response buffers and SDK imports can substantially
increase peak RSS. The 8,000,000-byte file limit does not cap decoded memory to8MB.
Use one worker; do not increase concurrency before measuring image peak memory.
There is no claim that512MB is sufficient for concurrent maximum-size uploads.

Current Gemini calls have20-second provider timeouts and at most4 tool rounds;
tool/DB time is additional. Supabase Data API calls use15-second timeouts;
Stage2 HTTP transport defaults to12seconds. These are per-call limits, not a single
request deadline. Uvicorn keep-alive5s controls idle connections, not request length.

[Render Free](https://render.com/docs/free) sleeps after15minutes idle and typically
takes about1minute to wake, has750shared workspace instance hours/month, ephemeral
files and possible quota/outbound-traffic suspension. Patient persistence belongs
in Supabase, never in local files. This is a Hackathon test service, not an uptime
guarantee. Do not add artificial keep-alive cron jobs or upgrade without approval.

The frontend's [Vercel external proxy](https://vercel.com/docs/limits) has a120-second
timeout. Cold wake-up plus model/tools may exceed it even though the Render process
is still running. A timeout is not proof a write failed; inspect persisted state
and use existing idempotency, never blindly repeat confirmation writes.
Hosted HTTP limits and proxy behavior must be checked in the first test deployment;
no unverified fixed Render request-duration guarantee is assumed here.

## First test deployment acceptance (owner approval required)

1. Confirm Linux Python3.12 dependency installation and resource check pass; retain
   dependency versions, build logs and reviewed commit SHA. Inspect settings names,
   never print secrets. Confirm no private/internal files are tracked in the release.
2. Check direct `/api/health`200 with `database=supabase`; unauthenticated
   `/api/me/preferences` must401; `/internal/notifications/dispatch` must404 on
   this patient service. Health reports wiring, not external-provider availability.
3. Exercise a synthetic JWT through the final frontend proxy: origin/CORS, Auth
   redirect/linking, owned profile and regimen, private image upload/readback, and
   errors. New browser origins do not automatically inherit localhost guest identity.
4. Compare direct and proxied cold/warm timings; test one bounded Gemini turn and
   Stage2 call only when approved. Capture Render memory/CPU during a representative
   photo, then a near-limit synthetic photo; attempt concurrent uploads only with
   safe headroom. Record OOM/restart/413/504 and stop load tests on resource pressure.
5. Check idle sleep/recovery, quota/provider failure and persistence after restart.
   Verify both languages and retry behavior with the UI integration owner.
6. Existing Supabase has owner-approved migration025 recorded; verify its ledger
   hash for the selected deployment target. Do not replay it in the Render build,
   or fix/deactivate legacy plans by running deployment scripts. New database
   targets need separate migration approval and acceptance.
7. Keep Push/Cron off until separate VAPID/dispatcher/permission/device acceptance.

Rollback of the patient release means selecting the previous reviewed API build
and matching frontend configuration, with owner approval. It does not roll back
the database or alter patient records.

References: [Blueprint specification](https://render.com/docs/blueprint-spec),
[Python selection](https://render.com/docs/python-version),
[Web Services](https://render.com/docs/web-services).
