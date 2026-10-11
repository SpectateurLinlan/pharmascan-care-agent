# WorkBuddy first sessions — empty-repository start

> This repo has **no application code yet**. Do not ask WorkBuddy to audit nonexistent backend/frontend source or assume that Stage 1 is ready. It can review the planning brief and external Stage 2 endpoint, then implement the minimal scaffold.

## Pre-flight (manual)

1. Create a private GitHub repository named `pharmascan-care-agent` (or team-approved alternative), without a second unrelated model repo merged into it.
2. Unzip the starter into the newly cloned local repository, e.g. `D:\Projects\pharmascan-care-agent`, and make the initial documentation commit.
3. Open that folder in WorkBuddy as its **working directory**. Ensure local Git and runtimes are installed. Work with synthetic data only.
4. Save official hackathon/challenge screenshots or handbook in a `docs/references/` directory only if you have redistribution rights; otherwise attach them to WorkBuddy from your own machine. Confirm submission portal details.
5. Ask the Stage 2 owner for a working request example, exact endpoint, output JSON/schema, API runtime constraints, and whether embeddings are exposed. Do not send credentials to chat.

## Session 1 — Ask — choose a low/mid-cost reliable tool-capable built-in model

```text
We are starting a NEW repository with planning documents only. There is currently no application code to audit. Read PROJECT_BRIEF.md and README.md, and review the attached Tencent Cloud Singapore 2026 Healthcare Challenge 2 instructions and scoring/submission requirements.

Context: The team name is PharmaScan and the proposed product is PharmaScan Care. We report an external Stage 2 pill-candidate recognition service at https://davidpansx-pharmascan-api.hf.space/ui/ but have not verified its exact inference endpoint, schema, or embedding availability. Stage 1 has NOT been implemented. A separately linked repository called ultrasound_Model is not verified as a pill-recognition codebase; do not clone it without checking.

Tasks:
1. Verify that the MVP scope is coherent for a patient-facing, voice-first medication companion and the six Challenge 2 capabilities.
2. Identify exact remaining unknowns in the Stage 2 API integration (do not invent routes, payloads or scores).
3. Produce a minimal vertical-slice architecture and implementation order for React/TypeScript, FastAPI, PostgreSQL/Supabase and a single tool-calling agent with deterministic safety checks.
4. Identify conflicts or unnecessary complexity in PROJECT_BRIEF.md, especially the new unlabelled clear-blister support.
5. Propose the first 2–3 commits and acceptance tests, without writing code yet.

Constraints: No doctor portal, NEHR integration, live patient data, automatic prescribing, unsafe medicine confirmation, or fabricated model metrics. Distinguish planned features from implemented features. Do not modify files in this Ask session. Return a concise review and at most five blocking clarification questions.
```

**Expected evidence:** screenshot showing WorkBuddy reading brief, identifying zero existing application code, and providing an actionable plan.

## Session 2 — Plan — architecture + minimal implementation

```text
Read PROJECT_BRIEF.md, README.md and your Session 1 audit. This is a bootstrap repository with no existing application implementation.

Create an actionable plan for the FIRST VERTICAL SLICE, not the whole product at once:
- FastAPI project scaffold, health endpoint and environment configuration
- PostgreSQL/Supabase schema and migrations for patient profile, medication product, patient medication, versioned regimen, schedule and dose event
- Typed API request/response models and synthetic test fixtures
- A minimal patient interface that can manually add a medication, review a regimen, record a self-reported dose event and display its history
- Unit/integration tests with a defined run command

Also define a Stage 2 API adapter interface, but do not implement a speculative endpoint contract until a real example is inspected. Stage 1 does not exist: initially support one clearly presented pill and an explicit unsupported/multi-pill state. Personal gallery embeddings and clear-blister matching are experimental and must not be treated as validated identity evidence.

Output: files/modules to create, dependency decisions, migrations, tests, acceptance criteria and a commit sequence. Save the approved plan under docs/ after review. Ask for approval before broad multi-file implementation. Do not build doctor or hospital modules.
```

## Session 3 — Craft — implement the first slice (once Session 2 approved)

```text
Implement only the approved first vertical slice from docs/, using the existing PROJECT_BRIEF.md. Create the necessary backend/frontend scaffolding and database migration. Run the application and tests with synthetic data. Demonstrate manual medication enrollment -> confirmed recorded regimen -> scheduled dose -> self-reported dose event -> history retrieval.

Do not claim a successful Stage 2 integration, Stage 1 implementation, medication recognition or voice interaction in this task. Do not invent API outputs. Keep secrets out of source and logs. On completion show actual files changed, exact commands run, test results and next unimplemented steps. If something fails, preserve the error and fix it with a repeatable test rather than reporting success.
```

## After the first slice

- Next: inspect live Stage 2 contract and implement a timeout-safe adapter; add OCR for readable packages and prescriptions.
- Next: design actual personal gallery encoder/capture protocol only after confirming whether Stage 2 embeddings are accessible. Add clear blister reference matching as an **unverified experimental** feature, with explicit abstention for unlabelled packages.
- Main WorkBuddy investment: plan and implement the **single Agent orchestrator** with typed tools, state, error recovery, deterministic safety gate and real tool traces.
- Last: patient UI accessibility, Challenge 2 health check-ins/preventive care/review summaries, integration test screenshots, demo and submission evidence.

## Model selection

Use a strong *built-in* WorkBuddy model that supports tool calling and file operations, if available. GPT-6 is not implied by having GPT-6 in ChatGPT. If the WorkBuddy selector truly offers GPT-6 with known cost, it can be used for architecture and agent coordination; otherwise use a suitable native option (e.g., Hy4 preview / GLM-5.3 / Kimi-K3 based on the actual installed menu). Fast/cheaper options suit small code corrections, while stronger modes suit cross-file agent design. Do not add an untrusted third-party API key solely to obtain a label.
