# Deployment entrypoints

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

See [patient deployment](../docs/RENDER_DEPLOYMENT.md) and
[notification deployment](../docs/REMINDERS.md).

## MediThread frontend routing

Configure the existing Vercel frontend project under **Settings > Build and
Deployment** (and Root Directory under the project's build settings):

| Setting | Value |
| --- | --- |
| Root Directory | `frontend` |
| Framework Preset | `Vite` |
| Install Command | `npm ci` |
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

After the patient API has an approved Render HTTPS hostname, copy
[the routing template](frontend/vercel.json.example) to `frontend/vercel.json`
and replace its explicit placeholder with that hostname. The template itself
is not deployable. Root `vercel.json` belongs exclusively to the Dispatcher;
never copy it into the frontend project. `VITE_API_TARGET` only affects local
Vite and does not configure production routing.

Use project name `medithread` for the frontend and a distinct worker project
name, such as `medithread-push-dispatcher`. These display names do not rename
the repository, Python packages or existing database. Keep Web Push disabled
for the initial core demonstration until its separate delivery acceptance.
