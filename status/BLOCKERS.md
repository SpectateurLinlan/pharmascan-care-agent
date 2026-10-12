# Blocking / uncertainty register

| ID | Issue | Owner | Safe action without user | Human action needed | Status |
|---|---|---|---|---|---|
| B01 | Actual Stage2 `/embed` `/match` `/identify` `/scan` responses not confirmed against latest deploy | Stage2 API owner | DTO mocks + adapter skeleton + schema tests; flag simulated | Share anonymized real JSON or stable OpenAPI | open |
| B02 | External Supabase project URL/auth keys not supplied | App/infrastructure owner | Write migrations and testable repositories, no live DB claims | Create free project, configure environment | open |
| B03 | LLM/ASR/TTS service keys not supplied | App/Agent owner | dependency-injected fake provider + deterministic agent tests | Supply keys through local secret manager | open |
| B04 | Main GitHub code and repository URL not inspected | App owner | inspect workspace when WorkBuddy starts | Verify correct local repo and git remote | open |
| B05 | Stage1 multi-pill detector unverified; single pill → duplicate boxes in `/scan` | Vision owner | guarded single-pill manual crop path + regression test | fix/demonstrate detector stability | open |
| B06 | Cover, social URL, demo video, final web URL missing | Submission owner | prepare slots, storyboard and checklist | create/upload externally | open |
| B07 | Exact submissions form marks for Architecture PPT and Demo optionality not independently verified | Submission owner | distinguish target from verified organiser requirement | inspect final submission portal | open |
| B08 | Stray reserved-name junk file `nul` (34 bytes) in repo root, created by an accidental `2>nul` redirect in Git Bash; agent tooling gets ACCESS_DENIED on delete/rename (likely open handle). Already `.gitignore`d, harmless to git ops | App owner | none (ignored by git) | from own terminal run: `del \\.\D:\Projects\pharmascan-care-agent\nul` | open |
| B09 | `npm install` does not fetch the platform-optional native binaries on this machine (`@rollup/rollup-win32-x64-msvc`, `@esbuild/win32-x64`). `vite build`/`vitest` fail with MODULE_NOT_FOUND until they are installed explicitly | App owner | already worked around: both were installed explicitly and are recorded in `frontend/package-lock.json`; build and tests pass | none, unless a clean `npm ci` on another machine reproduces it — then run `npm i @rollup/rollup-win32-x64-msvc @esbuild/win32-x64` | mitigated |
| B10 | No camera capture path and no live image pipeline in the UI. `[Check pill]` is deliberately disabled and labelled unavailable rather than faking a result | App/Vision owner | button rendered disabled with an explicit "unavailable" label and a "visual check not run" notice | requires the frozen Stage2 contract (B01) before a real capture+match flow can be built | open (by design) |
