# Source-of-truth order

This file is the current repository entry point.

For current implementation decisions, follow documents in this order:

1. AGENTS.md — mandatory engineering and safety constraints
2. docs/MASTER_SPEC.md — current product and Hackathon scope
3. docs/ARCHITECTURE.md — component ownership and dependencies
4. docs/API_CONTRACTS.md — current API boundaries
5. docs/DATA_MODEL.md — persistence model
6. docs/WORKFLOWS.md — business and Agent flows
7. docs/BUILD_PLAN.md — implementation order and acceptance criteria
8. docs/DECISION_LOG.md — rationale and superseded decisions

Documents under docs/archive/ are historical only and MUST NOT override current specifications.


# PharmaScan Care — START HERE / 今晚执行入口

**Snapshot:** 2026-10-13 (SGT) · **Submission target:** 2026-10-16 · **Grand Final:** 2026-11-03.  
**Team name:** PharmaScan · **Proposed agent/project name:** PharmaScan Care (confirm with team before submission).  
**Challenge:** Healthcare Track **Challenge 2**, *AI Healthier Every Day: Intelligent Support for Long-Term Self-Care*. Do NOT drift into Challenge 1 self-triage.

## 0. Current truth — no misleading checkmarks

- [x] Research/design hand-off: this documentation package prepared.
- [~] Stage 2: externally deployed Hugging Face API with `/embed`, `/match`, `/identify`, `/scan` declared, and user-shared UI screenshots. **Actual full JSON schema, calibration, production reliability remain unverified.** Another team member is changing/testing those API endpoints; avoid touching or assuming stability.
- [?] Existing GitHub main repository and `PROJECT_BRIEF.md`: user states they exist; THIS PACKAGE HAS NOT inspected their live contents. Do not claim repository code is implemented.
- [ ] Main backend / PostgreSQL schema / full Agent / patient PWA / production deployment: no verified runnable evidence supplied.
- [ ] Official submission evidence: WorkBuddy history, ≥3 genuine chat screenshots, demo/link/cover/repository URL to fill in.

Status legend: `[x] evidence confirmed`, `[~] partially known`, `[?] needs inspection`, `[ ] pending`; **do not convert design into implementation completion**.

## 1. What to do tonight (10/13, immediately)

1. Copy this package's files to the **ROOT** of your existing `D:\Projects\pharmascan-care-agent` repository (merge carefully; preserve any newer code). Keep `.codebuddy/` visible in the repo; do not blindly overwrite an existing `PROJECT_BRIEF.md` before comparing. The docs are intentionally written for an empty/early-stage repository.
2. Open WorkBuddy in that **specific local project directory**. First use **Ask** with `prompts/01_RECON_AND_CONTRACT_ASK.md` only if you have not audited the repository. Ask mode makes no code edits. For actual overnight work, **switch to Craft** and send `prompts/02_OVERNIGHT_BUILD_CRAFT.md`; Plan may pause and require approval, so do not leave only a planning task running unattended.
3. Give WorkBuddy *permission only for the repository* and safe commands. No full-disk Full Access. No secrets/patient records, no automatic cloud purchases/deployments. Let it write tests/documentation/backend/frontend in scope and commit locally only after tests; **never silently push or deploy**.
4. In the morning review `status/WORK_LOG.md`, `status/BLOCKERS.md`, tests and diffs. Then use `prompts/03_MORNING_INTEGRATION.md` and `prompts/04_FINAL_RELEASE_QA.md` as appropriate.
5. Save real screenshots of WorkBuddy at **architecture/contract**, **Agent tool integration** and **debugging/tests** milestones. Never recreate a log after the fact.

## 2. Canonical reading order for an engineering agent

1. `AGENTS.md` / `CODEBUDDY.md` — mandatory software engineering, security, medical and evidence constraints.
2. `docs/MASTER_SPEC.md` — scope, requirements, scenarios, business context, 6 challenge capabilities and acceptance.
3. `docs/ARCHITECTURE.md` — ownership and production/development topology, Agent Loop.
4. `docs/WORKFLOWS.md` — full medication lifecycle + six detailed branches and tool traces.
5. `docs/DATA_MODEL.md` — schema, fields, keys, constraints, versioning, storage and example source contracts.
6. `docs/API_CONTRACTS.md` — current vs proposed endpoints, adapter DTOs, Stage2 handoff, tests.
7. `docs/SAFETY_AND_EVALUATION.md` — risk/evidence boundary, safe rules, validation and metrics.
8. `docs/BUILD_PLAN.md` — executable priority checklist, dates, owners, acceptance and blocker management.
9. `docs/SUBMISSION.md` — all 10 submission portal fields, statuses, 100-point rubric.
10. `docs/DECISION_LOG.md` — reconciles Claude vs prior workflow conflicts.
11. `docs/WORKBUDDY_GUIDE.md` — staged usage, prompts, chat evidence, approval boundaries.

**Human-friendly Chinese/English interactive dashboard:** open `PharmaScan_Care_Master_Hub.html` offline. Checkboxes there are stored *only in your browser*; `status/tasks.json` + `docs/BUILD_PLAN.md` are the repository team source of truth.

## 3. Critical architecture decisions

- ONE patient-facing mobile-first portrait-primary PWA, tablet/landscape compatible; consent-based caregiver contact, no full caregiver/doctor interface. Simulated clinician/source actor is allowed in demo, but NO real Singpass/NEHR/hospital integration.
- Login demo: authenticated **anonymous per evaluator** seeded with independent clean synthetic multi-day records; team sign-in can use email/password. Do not share one editable patient account. Auth and RLS are non-negotiable; no real patient data.
- **React + TypeScript PWA**, **FastAPI**, **Supabase PostgreSQL + Auth + private Storage + pgvector**, **external Stage2 HF API**, **optional Tencent ASR/TTS**. Candidate frontend deploy Vercel, backend Railway *subject to available trials/terms*. WorkBuddy for development. **NO ADP for MVP**.
- Patient medication record/regimen identity is sourced from written medication guidance + user review, not Stage2 imagery. Unknown or mismatched pill image never becomes ground truth. Catalogue-derived image can prefill an **unverified visual candidate** only; personal loose pill photo can create patient reference after source linkage.
- Smart Check (photo optional) default: user reports taken/not taken/unsure separately from vision match. Never infer ingestion or safe dosing.
- WorkBuddy tonight's minimum vertical slice: synthetic demo → manual enrollment → active/historical regimen → one scheduled dose → optional image API adapter/mocked state → safe policy → user self-report → persisted event → stateful tool traces; then improve OCR/voice/health tracking.

## 4. References and caveats

- User-supplied 144-page retrospective PDF compiles previous analyses, *not necessarily a standalone official organiser specification*. The separate Hackathon brief screenshots and the user's current submission-portal field list are treated as submission requirements. Where earlier summaries conflict (e.g. optional vs user portal expecting a link/video/PPT), use `docs/SUBMISSION.md` to distinguish official base requirement, user requested target, and validation still needed.
- `docs/reference/PharmaScan_Care_Agent_Workflow_2026-10-12.html` and `docs/reference/WORKFLOW_SPEC_2026-10-12.md` are preserved, *not replaced*. Stage2 owner may already be following their endpoint design; coordinate changes instead of renaming or deleting any routes without agreement.
- `docs/reference/Claude_Medication_Lifecycle.html` provides the business lifecycle inspiration; previously noted API `read-label` and automated imprint capabilities are **not confirmed** by the existing v0.4.0 OpenAPI.
- Official model API: https://davidpansx-pharmascan-api.hf.space/docs ; UI https://davidpansx-pharmascan-api.hf.space/ui/ ; existing owner repo https://github.com/398-21/ultrasound_Model . Main repo URL: [FILL].
