# Deployment entrypoints

This file owns public service entry points and build/routing layout. It is not a live
infrastructure inventory or permission to publish. Dated local failures/results explain
constraints; verify the chosen artifact and environment before any approved release.
Detailed private operator procedures are maintained separately and are not public dependencies.

| Service | Files | Service root |
| --- | --- | --- |
| Vercel frontend | Existing `frontend/` Vite project | `frontend` |
| Render patient API | [render/render.yaml](render/render.yaml), `scripts/run_patient_api.py` | Repository root (leave Dashboard Root Directory blank) |
| Vercel Push Dispatcher | [dispatcher/index.py](dispatcher/index.py), root `pyproject.toml` / `vercel.json` | Repository root |

Render Blueprint Path: `deploy/render/render.yaml`. Auto Deploy is **On Commit**:
pushes to the linked branch trigger builds after the service is created/configured.
This is not automatic Git commit/push permission, and saving local files does not
update a hosted service. Import/create/deploy still requires owner approval.

The Vercel Dispatcher uses the documented custom Python module entrypoint in
`[tool.vercel]`. Root `vercel.json` and `.vercelignore` remain where Vercel's default
Git deployment discovery reads them. Moving the entry module does not require
moving the project root or copying dependencies into another project folder.
The frontend's Vercel project uses `frontend` as its root and does not serve this
privileged worker. Never share environment groups with the patient API/frontend.

Local ASGI routing/import tests verify the relocated module. Vercel Linux package,
subprocess runtime and real Push delivery still need an approved Preview deployment;
this layout change does not establish cloud readiness.

See [patient deployment](../docs/RENDER_DEPLOYMENT.md) and the
[worker dispatch trust boundary](../docs/ARCHITECTURE.md#worker-dispatch-transport-boundary).

## MediThread frontend routing

Configure the existing Vercel frontend project under **Settings > Build and
Deployment** (and Root Directory under the project's build settings):

| Setting | Value |
| --- | --- |
| Root Directory | `frontend` |
| Framework Preset | `Vite` |
| Install Command | `npm ci --include=dev` |
| Build Command | `npm run build` |
| Output Directory | `dist` |
| Node.js | `22.x` |

The application must not declare `@esbuild/win32-x64` or
`@rollup/rollup-win32-x64-msvc` directly, even as optional root dependencies.
Vite's esbuild/Rollup dependencies select the correct native packages through
their own optional dependencies. The lockfile intentionally contains multiple
operating systems; keep those transitive entries. Do not use `--force`,
`--ignore-platform`, or omit optional dependencies to hide platform errors.

A redeploy of an old Git commit still uses its old manifest and README. Verify
the deployment's source commit after the owner-approved release push; local edits
do not update GitHub or the existing Vercel project.

The committed `frontend/vercel.json` explicitly installs build dependencies and
runs the package build script. Leave Dashboard command overrides disabled, or
set them to exactly the values above. `vite build` alone is not the project build
command. Do not set `NPM_CONFIG_OMIT=dev` for this build.

The repository-level `.vercelignore` allows only the two projects and their
runtime dependencies. Unlisted root paths are excluded without naming local
materials in public configuration. `frontend/` remains available; its own
`.vercelignore` excludes credentials and generated files. The Dispatcher's
`functions.excludeFiles` separately excludes frontend from its Python bundle.
These upload rules do not control Git tracking or remove previously published
content from Git history.

Keep both repository-relative (`frontend/package-lock.json`) and project-relative
(`package-lock.json`) inputs in the frontend upload allowlist. Git build filtering
and local project uploads can use different path bases. To check both before
publication, install frontend dev dependencies and run
`node tests/check_vercel_inputs.cjs` from the repository root. Testing only paths
relative to `frontend/` can miss a removed lockfile in a Git deployment.

The frontend's committed API rewrite targets
`https://medithread-patient-api.onrender.com/api/:path*`, retaining the suffix and
incoming query parameters. The SPA fallback explicitly excludes `/api` paths;
API errors must not become successful HTML responses. Existing static assets
are served by Vercel's filesystem routing. Root `vercel.json` remains exclusively
the Dispatcher configuration. Do not copy it into the frontend project.

Patient HTTP clients use same-origin `/api/...`; `VITE_API_BASE_URL` is not read.
Do not configure it to bypass the proxy. `VITE_API_TARGET` is a local Vite dev
proxy setting only. Vercel Production needs `VITE_SUPABASE_URL` and
`VITE_SUPABASE_PUBLISHABLE_KEY` for the same existing project as Render. These
are public identity configuration; never add server-only credentials. Environment
changes require a new frontend build.

Production origin is `https://medithread.vercel.app`. The Render service's
`APP_ORIGIN` must equal this exact origin (no trailing slash). Supabase Auth
Site URL and allowed Redirect URLs must include this frontend origin; enable
anonymous sign-in for the existing guest workflow. Email login/linking uses
`window.location.origin`. Do not substitute the Render API URL as the callback.
Preview deployments need separately approved origins/callbacks; do not add a
blanket wildcard or relax backend CORS.

After publishing the approved revision, check frontend `/api/health` returns
Render JSON (not HTML), an unauthenticated patient route returns401, and Auth
callback/hash navigation restores normally. Then run isolated synthetic
Enrollment/B14, Gemini tools and saved-conversation checks. Health values
`gemini_configured` and `stage2_vision=live` indicate wiring, not successful
provider execution. The reusable [routing template](frontend/vercel.json.example)
still requires an explicit hostname when adapting the project for another host.

Use project name `medithread` for the frontend and a distinct worker project
name, such as `medithread-push-dispatcher`. These display names do not rename
the repository, Python packages or existing database. Web Push requires separate
Dispatcher hosting, Cron and real-device receipt before release acceptance.
