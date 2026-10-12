# PharmaScan Care — Tencent Cloud Hackathon 2026 Healthcare Track

**Status: documentation handoff only (2026-10-13), not a finished software implementation.** Team: PharmaScan; proposed AI-agent name: PharmaScan Care; Healthcare Challenge 2. Submission target: 2026-10-16 (cutoff time to verify). The independently hosted Stage2 visual service already exists, but the main app/agent/deployment must be built and verified.

**START HERE:** [`00_START_HERE.md`](00_START_HERE.md) — safe overnight setup and reading order.

**Interactive planning hub:** open [`PharmaScan_Care_Master_Hub.html`](PharmaScan_Care_Master_Hub.html) in your browser. It includes bilingual navigation, 6 interactive flow diagrams, first-screen submission statuses, 60 checkable tasks, WorkBuddy prompts and source links. Local checkmarks are **browser-local only**; repository state of truth is [`status/tasks.json`](status/tasks.json).

**English engineering specs:** [`PROJECT_BRIEF.md`](PROJECT_BRIEF.md) is an index; read [`docs/MASTER_SPEC.md`](docs/MASTER_SPEC.md), [`docs/WORKFLOWS.md`](docs/WORKFLOWS.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/API_CONTRACTS.md`](docs/API_CONTRACTS.md), [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md), [`docs/SAFETY_AND_EVALUATION.md`](docs/SAFETY_AND_EVALUATION.md), [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md), [`docs/SUBMISSION.md`](docs/SUBMISSION.md), [`docs/WORKBUDDY_GUIDE.md`](docs/WORKBUDDY_GUIDE.md).

**中文版：** [`中文总览.md`](中文总览.md).

**Mandatory engineering rules:** [`AGENTS.md`](AGENTS.md), [`CODEBUDDY.md`](CODEBUDDY.md), [`.codebuddy/rules/engineering/RULE.mdc`](.codebuddy/rules/engineering/RULE.mdc) for CodeBuddy IDE. Standalone WorkBuddy may not auto-load these; all prompts explicitly direct it to read rules.

**Night prompts:**
- Ask: [`prompts/01_RECON_AND_CONTRACT_ASK.md`](prompts/01_RECON_AND_CONTRACT_ASK.md)
- Unattended Craft: [`prompts/02_OVERNIGHT_BUILD_CRAFT.md`](prompts/02_OVERNIGHT_BUILD_CRAFT.md)
- Morning integration: [`prompts/03_MORNING_INTEGRATION.md`](prompts/03_MORNING_INTEGRATION.md)
- Final QA: [`prompts/04_FINAL_RELEASE_QA.md`](prompts/04_FINAL_RELEASE_QA.md)

**Infrastructure intent**: React TypeScript Mobile-first PWA, FastAPI agent + typed tools + deterministic policy, Supabase PostgreSQL/Auth/pgvector/private Storage, Hugging Face PharmaScan Stage2 API, optionally Tencent ASR/TTS, possibly Vercel/Railway hosting after cloud setup. No Tencent Cloud ADP. Use synthetic patients only, never upload real medication records. Stage2 owner maintains his own code; the main repo consumes a stable versioned adapter.

## Merge warning

This documentation package is meant to be merged into the existing repository, not to replace live code. **Back up/diff existing `PROJECT_BRIEF.md`, `README.md` and `.gitignore` before copying.** Preserve other team branches and working model APIs. Do not claim anything is implemented without actual tests.
