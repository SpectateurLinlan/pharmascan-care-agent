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
