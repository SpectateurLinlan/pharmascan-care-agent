# Human deployment preparation (no deployment performed)

Local QA does not establish deployed-production readiness. Vercel routing/entrypoint configuration is not present in this checkout; frontend uses same-origin /api routes and the Vite localhost proxy is development-only. Existing FastAPI app.transport.app_factory:create_app is the verified ASGI entrypoint. Prepare a Python function adapter or a separately hosted backend plus /api rewrite before deployment; verify frozen docs/external Stage2 OpenAPI JSON is packaged when label extraction is enabled. Do not depend on local .env or editable-install paths.

1. Finish physical Chrome/Edge microphone/transcript/edit/Send/response/browser TTS play-stop/B14/history acceptance with synthetic data.
2. Review current dirty tree, deployment adapter/API routing, selected free runtime limits and bundled contract path. Confirm repository licence/third-party notices before publication; no project LICENSE currently exists.
3. Set server-only PERSISTENCE=supabase, AUTH_MODE=supabase, SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, APP_ORIGIN, STT_PROVIDER=browser, TTS_PROVIDER=browser, and VISION_API_BASE_URL when using label extraction. DATABASE_URL is not required for patient runtime. Keep all credentials server-side.
4. Browser-only variables: VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY. Never give browser a secret/service-role key. Use HTTPS for real-device voice; browser support is feature-detected, with typing fallback.
5. After obtaining an actual deployment URL, human configures Supabase Site URL/Redirect URLs as relevant and APP_ORIGIN; then runs deployed smoke checks. Do not assume local localhost origin or preview URL is a production origin.

Deployed smoke checks: health; unauthenticated401; fresh anonymous A/B ownership isolation; reviewed source/manual enrollment; scheduled/PRN independent confirmation and replay; Stage2 failure/manual fallback; voice unsupported/permission/error/edit/Send/TTS play-stop; reminder snooze/status/denied notification fallback/no regimen or intake mutation; frontend bundle has no server secrets. No closed-browser delivery claim.

Submission remains human-owned: actual cover/video/deployed URL/architecture PPT/GitHub accessibility, qualifying genuine Tencent-tool history and at least three genuine screenshots. Never substitute synthetic browser QA screenshots for WorkBuddy chat evidence.


Personalised runtime additions: set server-only MODEL_PROVIDER=gemini,GEMINI_API_KEY,GEMINI_MODEL=gemini-3.5-flash-lite,GEMINI_THINKING_LEVEL=low,DEMO_AGENT_DAILY_TURN_LIMIT=20. Confirm migrations008-012 and private quota cap; keep direct usage DML denied and same-user JWT repositories. Do not give deployment runtime DATABASE_URL merely to execute patient operations.

Before recording/deploying, manually reaccept Metformin500mg20:00 review/activate/reload/Today, it follow-up, uncertainty/B14, English and Chinese speech/TTS and persisted preference, real Stage2 photo evidence, reminder state and quota disclosure. Tencent English1050 and Chinese1001 mapping stays server-side; both provider API evidence and physical playback must be distinguished. No paid-tier/3.6 automatic fallback. Hosting entrypoint/rewrite, licence and genuine submission artefacts remain unprepared human decisions.


Email Auth manual setup/acceptance (not changed by Codex):
- Keep existing browser publishable variables; no new secret is needed in React.
- Enable email sign-in and verify SMTP/allowed test recipient delivery, rate limits and CAPTCHA if configured. Read-only development settings report email enabled and autoconfirm=false; delivery is NOT live verified.
- Add actual local/production origins to Auth redirect allowlist/Site URL as appropriate. The app requests window.location.origin; do not assume an unlisted redirect is honored.
- For both OTP and Magic Link, configure Magic Link/email-change templates with both {{ .Token }} and {{ .ConfirmationURL }}. Do not place token/hash/code in logs, screenshots or repository examples.
- Enable manual identity linking if using anonymous -> email upgrade; verify the same auth.uid and records after email confirmation. Existing-account login intentionally switches identity and does not merge guest records. Password fallback can be set after email verification.
- Test email/link expiry, invalid code/password, rate limit, callback URL cleanup, reload and cross-tab identity changes with your own test mailbox. Singpass remains a disabled placeholder.
- Apply013 with owner FORCE RLS and no direct feedback UPDATE/DELETE; test feedback B isolation. Test all-medication due prompts/lead/snooze/reopen/no-background promise.

Official references: https://supabase.com/docs/guides/auth/auth-anonymous and https://supabase.com/docs/guides/auth/auth-email-passwordless .

Patient-experience gate: apply migration014 via python scripts/db.py migrate --only 202610140014 after verifying earlier ledger hashes. Confirm new health table FORCE-RLS/owner FK/DML isolation. Reaccept two-action B14/Cancel/retry, health save/edit/delete/reload, week/month/course summary and intentional export, Me/profile/account and browser Back draft retention at390/430px. Caregiver management is PARTIAL; personal-gallery matching now has real synthetic integration/browser evidence; no background push or automatically shared records. New Gemini health tool/severe-symptom behavior needs provider/manual acceptance; do not interpret mocked tool tests as live Gemini verification.

Recheck simultaneous Today/history/reminders requests return200 without duplicate occurrences, and summary windows over page limits report a clear failure rather than incomplete totals. Speak/enter a serious-symptom description: conditional help must precede model/medication actions, without automatic health/dose persistence. This is not an emergency/triage service. Public runtime uses relative /api paths; production hosting adapter/rewrite, HTTPS/origins, actual email linking and physical voice must still be prepared and verified by a human.

## Current voice cost boundary (2026-10-14; supersedes earlier TTS defaults)
Browser STT review/Send and the existing Agent/B14/RLS path are unchanged. Default playback is frontend Browser SpeechSynthesis, not a backend request. Actual language-qualified voices load via getVoices/voiceschanged; localService preference, en-SG/English fallback and zh-SG/zh-CN Mandarin only. Missing/failed voices preserve text and never invoke Tencent. Rate defaults to 0.9x; generation guards cancel old playback on Stop/new turn/navigation/language/provider/autoplay changes.

Optional cloud requires server TTS_PROVIDER=tencent plus existing ENABLE_SPEECH/TENCENT_SPEECH_APPROVED credentials configuration AND explicit session-only patient selection. Request provider=tencent and consent are mandatory; reload restores browser. Default .env.example/.env use TTS_PROVIDER=browser. Browser STT/TTS may use online services, not guaranteed offline. No new billing activation, provider calls or migration. See README Voice cost policy for enablement details.

Chrome/Edge native API presence and injected en/zh playback lifecycle are AUTOMATED/SYNTHETIC. Headless native voice lists were empty. Physical microphone/speaker, actual installed voices, medicine/dose pronunciation, autoplay/Stop/replay and missing-language typed fallback remain MANUAL PENDING before deployment. Historical real Tencent WAV evidence does not verify browser audio.


## Evidence/gallery release checks (2026-10-15)

Apply migrations015-018 after prior ledger/hash verification. Confirm six new tables FORCE RLS, owner compositeFK, image metadata retirement trigger, atomic store_personal_reference and evidence activation guard. Normal runtime still needs no DATABASE_URL. Keep visual-references private, authenticated proxy and same-user JWT; no public image links or service-role fallback.

Run bounded Demo A/B/C with synthetic fixtures using current workflows. Check private thumbnail/reload, actual embedding metadata, eligible owned personal references, real match evidence, historical/current/source-conflict abstention, deliberate retirement and A/B isolation. Compare capture at390/430px and desktop; test real camera/keyboard and physical voice separately. PDF/whole-blister matching remains unavailable. Do not use identical synthetic photo matching as clinical accuracy evidence. No shared-database rollback was executed.
