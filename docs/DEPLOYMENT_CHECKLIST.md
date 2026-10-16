# Human deployment preparation (no deployment performed)

## Current release topology and operator procedure

Selected MVP topology: Vercel static frontend, Render Free patient FastAPI,
existing Supabase Auth/PostgreSQL/private Storage, and a separate Vercel Push
Dispatcher invoking the existing bounded worker. No deployment has been performed.
Hosting/accounts, Secrets, migrations and any billed capacity need owner approval.
See [Render patient deployment](RENDER_DEPLOYMENT.md) for the prepared build,
startup, health, environment isolation and first-test-deployment checks.

1. Build from the repository checkout with Node22.12+ and Python3.11+. Keep
   `backend/`, `docs/external/` and `scripts/` together. The current adapter loads
   its frozen contract relative to source; a wheel alone does not package it.

   ```sh
   python -m venv .venv
   . .venv/bin/activate
   python -m pip install '.[push]'
   export PYTHONPATH="$PWD/backend"
   test -f docs/external/pharmascan-api-openapi-0.10.0.json
   npm --prefix frontend ci
   npm --prefix frontend run build
   ```

2. Configure the API process through the hosting secret store:
   `PERSISTENCE=supabase`, `AUTH_MODE=supabase`, `ENABLE_DEMO_SEED=false`,
   `APP_ORIGIN=https://app.example.invalid`, `SUPABASE_URL`,
   `SUPABASE_PUBLISHABLE_KEY`, `MODEL_PROVIDER=gemini`, `GEMINI_API_KEY`,
   `GEMINI_MODEL=gemini-3.5-flash-lite`, and `VISION_API_BASE_URL`.
   Current voice defaults are `STT_PROVIDER=browser`, `TTS_PROVIDER=browser`.
   Keep `ENABLE_WEB_PUSH=false` on the patient API. For device subscriptions,
   configure `ENABLE_PUSH_SUBSCRIPTIONS=true` and the matching public VAPID key.
   Do not give the patient API privileged `DATABASE_URL`/service-role keys.
   From the checkout, with the virtual environment active:

   ```sh
   python -m uvicorn app.transport.app_factory:create_app --factory --host 0.0.0.0 --port 8000
   ```

   Put TLS and a supervised restart policy in front of it. Review provider
   outbound access/timeouts and sufficient HTTP proxy timeout for bounded model
   rounds. `/api/health` reports wiring; it does not probe every dependency or
   establish OCR correctness. Verify actual authenticated owner requests too.

3. For a Vercel static project, root directory is `frontend`, install command
   `npm ci`, build command `npm run build`, output `dist`. Build-time browser
   variables are ONLY `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`.
   `VITE_API_TARGET` is a development proxy setting, not a production API URL.
   Before an approved deployment, create a project `vercel.json` using the actual
   backend host in this example (the reserved example domain is not deployable):

   ```json
   {
     "rewrites": [{"source": "/api/:path*", "destination": "https://api.example.invalid/api/:path*"}],
     "headers": [
       {"source": "/api/:path*", "headers": [{"key": "Cache-Control", "value": "private, no-store"}]},
       {"source": "/sw.js", "headers": [{"key": "Cache-Control", "value": "no-cache"}]}
     ]
   }
   ```

   The hash router needs no catch-all rewrite. Preserve `/api` and Authorization
   headers; smoke-test multipart uploads, JSON errors,401/404 and downloads
   through the final proxy. Do not CDN-cache patient API responses. The service
   worker has root scope, handles Push/clicks and does not cache patient data.
   An equivalent HTTPS reverse proxy/static host is also suitable. See
   [Vercel external rewrites](https://vercel.com/docs/routing/rewrites).

4. On the operator's separate migration environment, run `python scripts/db.py
   status` and `verify`, compare the full ledger with all current migration
   files, then review any genuinely pending additive migration before applying.
   Existing Supabase has001–025 applied; do not reset, roll back or edit them. Never
   infer ledger compatibility from a build or from `verify` alone.

5. Manually configure Supabase Site URL/redirect allowlist for the actual HTTPS
   origin and accept anonymous→email linking with a synthetic identity. Browser
   storage and anonymous sessions are origin-specific; a new origin does not
   automatically recover the old guest identity. Existing-account login is an
   explicit identity switch, not a record merge. Do not clear Auth storage.

6. Only after approved VAPID configuration, give the isolated worker
   `DATABASE_URL`, VAPID public/private/subject, `ENABLE_WEB_PUSH=true` and its
   dedicated HMAC token. Do not copy Gemini or patient API secrets. For a
   supervised local worker check, from the checkout/virtualenv run
   `python scripts/run_reminders.py --loop`. It polls every30seconds, uses the
   existing durable queue, bounded delivery/retries and clinical eligibility
   checks. Keep it independent of browser lifetime; monitor/restart failures.
   This code path is not a guaranteed minute-level delivery SLA. No configured
   always-on host or production worker has been verified. Vercel Hobby Cron is
   daily with hour-level precision and cannot serve this scheduling need; see
   [current Cron limits](https://vercel.com/docs/cron-jobs/usage-and-pricing).
   No paid plan is enabled or presumed necessary without an owner choice.

7. Accept permission, subscription persistence, provider acceptance, actual
   device receipt and notification click independently. iOS/iPadOS16.4+ Push
   requires a Home Screen web app and a permission request following user
   interaction, not an ordinary Safari tab; see
   [WebKit platform requirements](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/).
   Test Windows Chrome/Edge, Android PWA and iPhone with generic private content,
   logout/revocation and authenticated deep links. Actual Push delivery, mobile
   keyboard/audio and calendar-client imports remain manual acceptance gates.

Deployment smoke: HTTPS assets/SW; API wiring; anonymous unauthenticated401;
synthetic A/B isolation; reviewed enrollment/activation/reload; independent B14
and replay; stock/task idempotency; image provider failure/manual fallback;
review/export; no server secrets in bundles. Check current provider quotas,
runtime sleep/egress/storage costs and third-party privacy/licence terms before
approving hosting. No free plan is assumed to provide continuous operation.

## Long-term care release gate (2026-10-16)

- Recorded database baseline is001–025 after owner-authorized025 application on2026-10-16; prior001–024 checksums matched and were not replayed. Do not reinitialize or edit earlier checksums. Keep FORCE RLS and prior source/B14 guards intact. The025 overlap guard is an explicit conservative MVP limitation, not clinical duplicate-therapy advice; existing records are retained. Future environment deployments still need their own ledger/hash check and approval.
- Patient HTTP needs only the existing verified user JWT/publishable configuration. No new provider, key or billed service is required by inventory/trends/review. Never expose DATABASE_URL to the frontend or select it as patient fallback.
- Upgrade the independent reminder worker with the schema: it now projects care tasks into the same delivery queue. Enable only the isolated worker for an approved real-device test after VAPID/HTTPS/operator checks; require permission, subscription, delivery and click before release acceptance. Queue acknowledgement is not device receipt.
- Re-run the synthetic E/F checklist in [LONG_TERM_CARE](LONG_TERM_CARE.md), plus existing A/B/C and B14 acceptance. Check a new account cannot read prior patient's tasks/ledger/source/observations.
- Deploy matching Agent/context-reader versions: the optional bounded `care_clarification` marker is backward-compatible with older stored contexts, but an older application reader may reject newly written fields. Verify visit preparation includes saved symptoms and follow-ups, and never allows a narrow task-only read to stand in for a full review. Development Chrome/Gemini verification now covers Agent proposal → human save → new-session symptom/task review → human-confirmed completion; it does not prove deployed or device Push delivery.
- Physical speech, calendar-client import, account linking and deployment require independent acceptance. No deployment is implied by automated test results.

Local QA does not establish deployed-production readiness. Root vercel.json and pyproject.toml select deploy/dispatcher/index.py for the independent Push Dispatcher only. Patient Render configuration is deploy/render/render.yaml (Auto Deploy On Commit, service root still the repository root). Frontend uses same-origin /api routes; its Vite localhost proxy is development-only. The prepared Render launcher uses existing FastAPI app.transport.app_factory:create_app and needs the final HTTPS frontend /api rewrite. Verify frozen docs/external Stage2 OpenAPI JSON is retained. Do not depend on local .env or editable-install paths.

1. Finish physical Chrome/Edge microphone/transcript/edit/Send/response/browser TTS play-stop/B14/history acceptance with synthetic data.
2. Review current dirty tree, deployment adapter/API routing, selected runtime limits and bundled contract path. Apache-2.0 LICENSE/NOTICE exist; retain all applicable third-party notices before distribution.
3. Set server-only PERSISTENCE=supabase, AUTH_MODE=supabase, SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, APP_ORIGIN, STT_PROVIDER=browser, TTS_PROVIDER=browser, and VISION_API_BASE_URL when using label extraction. DATABASE_URL is not required for patient runtime. Keep all credentials server-side.
4. Browser-only variables: VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY. Never give browser a secret/service-role key. Use HTTPS for real-device voice; browser support is feature-detected, with typing fallback.
5. After obtaining an actual deployment URL, human configures Supabase Site URL/Redirect URLs as relevant and APP_ORIGIN; then runs deployed smoke checks. Do not assume local localhost origin or preview URL is a production origin.

Deployed smoke checks: health; unauthenticated401; fresh anonymous A/B ownership isolation; reviewed source/manual enrollment; scheduled/PRN independent confirmation and replay; Stage2 failure/manual fallback; voice unsupported/permission/error/edit/Send/TTS play-stop; reminder snooze/status/denied notification fallback/no regimen or intake mutation; frontend bundle has no server secrets. No closed-browser delivery claim.



Personalised runtime additions: set server-only MODEL_PROVIDER=gemini,GEMINI_API_KEY,GEMINI_MODEL=gemini-3.5-flash-lite,GEMINI_THINKING_LEVEL=low,DEMO_AGENT_DAILY_TURN_LIMIT=20. Confirm migrations008-012 and private quota cap; keep direct usage DML denied and same-user JWT repositories. Do not give deployment runtime DATABASE_URL merely to execute patient operations.

Before deploying, manually reaccept image/manual review/activate/reload/Today, follow-up, uncertainty/B14, English and Chinese speech/TTS and persisted preference, real Stage2 photo evidence, reminder state and quota disclosure. Browser speech is the runtime default; optional Tencent English1050 and Chinese1001 mapping stays server-side. Provider API evidence and physical playback are distinct. No paid-tier/3.6 automatic fallback. Hosting and device acceptance remain operator decisions.


Email Auth manual setup/acceptance (not changed by Codex):
- Keep existing browser publishable variables; no new secret is needed in React.
- Enable email sign-in and verify SMTP/allowed test recipient delivery, rate limits and CAPTCHA if configured. Read-only development settings report email enabled and autoconfirm=false; delivery is NOT live verified.
- Add actual local/production origins to Auth redirect allowlist/Site URL as appropriate. The app requests window.location.origin; do not assume an unlisted redirect is honored.
- For both OTP and Magic Link, configure Magic Link/email-change templates with both {{ .Token }} and {{ .ConfirmationURL }}. Do not place token/hash/code in logs, screenshots or repository examples.
- Enable manual identity linking if using anonymous -> email upgrade; verify the same auth.uid and records after email confirmation. Existing-account login intentionally switches identity and does not merge guest records. Password fallback can be set after email verification.
- Test email/link expiry, invalid code/password, rate limit, callback URL cleanup, reload and cross-tab identity changes with your own test mailbox. Singpass remains a disabled placeholder.
- Apply013 with owner FORCE RLS and no direct feedback UPDATE/DELETE; test feedback B isolation. Test all-medication due prompts/lead/snooze/reopen/no-background promise.

Official references: https://supabase.com/docs/guides/auth/auth-anonymous and https://supabase.com/docs/guides/auth/auth-email-passwordless .

Patient-experience gate: apply migration014 via python scripts/db.py migrate --only 202610140014 after verifying earlier ledger hashes. Confirm new health table FORCE-RLS/owner FK/DML isolation. Reaccept two-action B14/Cancel/retry, health save/edit/delete/reload, week/month/course summary and intentional export, Me/profile/account and browser Back draft retention at390/430px. Caregiver management is PARTIAL; personal-gallery matching now has real synthetic integration/browser evidence; background Web Push requires the separate021/VAPID/worker setup below; no automatic record sharing. New Gemini health tool/severe-symptom behavior needs provider/manual acceptance; do not interpret mocked tool tests as live Gemini verification.

Recheck simultaneous Today/history/reminders requests return200 without duplicate occurrences, and summary windows over page limits report a clear failure rather than incomplete totals. Speak/enter a serious-symptom description: conditional help must precede model/medication actions, without automatic health/dose persistence. This is not an emergency/triage service. Public runtime uses relative /api paths; production hosting adapter/rewrite, HTTPS/origins, actual email linking and physical voice must still be prepared and verified by a human.

## Current voice cost boundary (2026-10-14; supersedes earlier TTS defaults)
Browser STT review/Send and the existing Agent/B14/RLS path are unchanged. Default playback is frontend Browser SpeechSynthesis, not a backend request. Actual language-qualified voices load via getVoices/voiceschanged; localService preference, en-SG/English fallback and zh-SG/zh-CN Mandarin only. Missing/failed voices preserve text and never invoke Tencent. Rate defaults to 0.9x; generation guards cancel old playback on Stop/new turn/navigation/language/provider/autoplay changes.

Optional cloud requires server TTS_PROVIDER=tencent plus existing ENABLE_SPEECH/TENCENT_SPEECH_APPROVED credentials configuration AND explicit session-only patient selection. Request provider=tencent and consent are mandatory; reload restores browser. Default .env.example/.env use TTS_PROVIDER=browser. Browser STT/TTS may use online services, not guaranteed offline. No new billing activation, provider calls or migration. See README Voice cost policy for enablement details.

Chrome/Edge native API presence and injected en/zh playback lifecycle are AUTOMATED/SYNTHETIC. Headless native voice lists were empty. Physical microphone/speaker, actual installed voices, medicine/dose pronunciation, autoplay/Stop/replay and missing-language typed fallback remain MANUAL PENDING before deployment. Historical real Tencent WAV evidence does not verify browser audio.


## Evidence/gallery release checks (2026-10-15)

Apply migrations015-018 after prior ledger/hash verification. Confirm six new tables FORCE RLS, owner compositeFK, image metadata retirement trigger, atomic store_personal_reference and evidence activation guard. Normal runtime still needs no DATABASE_URL. Keep visual-references private, authenticated proxy and same-user JWT; no public image links or service-role fallback.

Run bounded Demo A/B/C with synthetic fixtures using current workflows. Check private thumbnail/reload, actual embedding metadata, eligible owned personal references, real match evidence, historical/current/source-conflict abstention, deliberate retirement and A/B isolation. Compare capture at390/430px and desktop; test real camera/keyboard and physical voice separately. PDF/whole-blister matching remains unavailable. Do not use identical synthetic photo matching as clinical accuracy evidence. No shared-database rollback was executed.

## Daily interaction smoke checks (2026-10-15)

After restarting the current backend/frontend, check today's medicine actions start collapsed and only the selected card expands. Confirm the renamed Compare a pill photo entry opens camera/upload with purpose/limitations. Ask today's plan and due-now separately: answers must name medicines, reviewed quantities and times, including future times for today, and respect the patient's timezone. Verify no dose event before the separate B14 confirmation. First-use guide must be skipped/finished before recording existing demo journeys. Current automated UI checks use synthetic API/Auth; real Gemini and physical device checks for this revision remain manual/live acceptance pending.

Local assets/submission media, uploads, screenshots, internal status/prompts and tool workspaces are ignored; assets/README.md is removed only from the Git index and retained locally. Runtime icons/manifest, migrations, source, lockfiles and synthetic regression fixtures stay versioned. Distribute approved submission media separately; no history rewriting or automatic publication.

## Numeric text and daily overview (2026-10-15)

Apply migration019 only after001-018 hashes match (development application is already verified); restart backend so the typed numeric preference field is accepted. Never replay/alter older migrations or roll back shared user preferences. Test100/125/150% by mouse/touch and keyboard, reload and A/B profile isolation. All fonts must scale, text must wrap/scroll without horizontal overflow, and header/nav/composer must remain separated. Test three medicines, PRN, same-name different doses, direct selection, previous/next and physical swipe. Reminder navigation must select its actual regimen; hidden slides must stay inert. Report actions must still use B14 and create no event before confirmation. Synthetic automated UI and real Supabase preference evidence do not verify physical touch/voice hardware or deployment.

## Private caregiver contact management (2026-10-15)

Migration020 development applied only after001-019 hashes matched; rollback not run. Before demo, restart backend and open Me -> Caregiver contacts. Add synthetic name/email, explicitly check storage permission, save and reload, edit and confirm/cancel delete. Check unverified/notifications-off/no-record-access labels. No email/SMS/invitation should occur, and no provider credential is needed. Verify25 required tables retain FORCE RLS and normal contact CRUD uses same-user JWT, not DATABASE_URL. Verified recipient status, account linking, caregiver notifications and medical-record access remain future capabilities.

## Stage2 0.10.0 upgrade gate

- Keep the existing VISION_API_BASE_URL; include the0.10.0 contract in the backend package and restart current gateways. No migration is required.
- Read health/model-info/tools as JSON; distinguish API/model/space/preprocess/dimension/normalization and retain calibration provenance. Reject incompatible vectors; GET wakeup retries are bounded, uploads are never retried implicitly.
- Repeat upgraded Demo A/B/C from STAGE2_V010_UPGRADE.md. Prior0.8/0.9 evidence is not a substitute. Verify explicit patient review, source conflict retention, owned gallery and B14.
- PDF, whole-blister matching and automatic catalogue fallback remain partial/inactive; no closed coverage or medical-safety claim. Do not enable DDInter screening commercially without permission/validation. Never enable feedback/training from ordinary gallery consent.

## Proactive reminder release prerequisites (2026-10-15)

Apply additive021 (development applied; no reset/rollback). Normal HTTP still needs only user-JWT Supabase; do not give it privileged DB fallback. Install optional `[push]` dependencies for the separate worker. Generate/store VAPID privately, configure operator subject and enable explicitly on API/worker; use HTTPS and a supervised worker or durable external scheduler independent of browsers. Instructions: [Reminders](REMINDERS.md). No hosting, VAPID enablement or external push was performed by this session.

Accept service-worker registration, permission, subscription persistence, provider-accepted send, actual device receipt and notification click independently. Check Windows Chrome/Edge, Android PWA and iOS16.4+ Home Screen web app; denied/unsupported still use in-app and calendar. Test logout/revoke, changed/stopped plans and no B14 bypass. Import real `.ics` into Apple/Google/Outlook and check timezone/VALARM/manual stale-event removal. P2 native alarms remain future-only. Existing physical voice/email/submission gates remain.

Restart both application servers for internal runtime contract `patient-ux-reminders-v1`; do not leave an old8001 server behind a new Vite UI. This avoids late422/404 errors from old preference/reminder endpoints. Preserve Auth storage. The source SDK's email callback is consumed before hash-router initialization. Optional worker startup is documented separately; `scripts/start_dev.py` still starts the normal two development servers and does not silently enable notifications.

## Session 04.5 integration gate

- Apply additive024 only after checking earlier migration ledger; verify31 patient tables with ENABLE/FORCE RLS. Never edit an applied migration or reset patient data.
- Restart backend after updating typed source/history/preference contracts. Anonymous sessions remain intact; archive saving defaults off.
- Install declared psycopg base dependency. Windows native npm binaries are optional for cross-platform installs. A fresh Linux installation still needs independent CI acceptance.
- Keep secrets server-side; Apache project licensing does not relicense providers, DDInter or other external datasets. Retain upstream notices when distributing dependencies.
- Perform final device acceptance of keyboard/speech, account linking, actual calendar import and Push receipt/click. HTTPS/VAPID/supervised worker remain deployment prerequisites, not inferred from code checks.
- Session04.5 does not constitute Session05 deployment approval.
# Protected Web Push dispatcher deployment handoff

Local code now includes a separate request-bounded HMAC dispatcher; deployment,
credentials, Cron and device receipt are still human gates. Prefer a separate
Vercel Python project for Worker secrets, subject to packaged child-process/DB
smoke acceptance; Render Free is a standard-process fallback with idle/hour limits.
Do not share DATABASE_URL or PUSH_DISPATCH_TOKEN with the patient API project.
Keep ENABLE_WEB_PUSH=false on the patient API. Configure
ENABLE_PUSH_SUBSCRIPTIONS=true and the matching VAPID_PUBLIC_KEY there; keep
ENABLE_WEB_PUSH=true plus the private key only in the isolated Dispatcher after
owner approval. Web Push receipt is now a required release gate. Follow
[the current Worker/operator procedure](REMINDERS.md#deployment-decision-and-human-configuration-gate),
including pg_net queued-header visibility and both migration ledgers. No job,
extension, schema, role, policy or cloud resource was changed by this implementation.
