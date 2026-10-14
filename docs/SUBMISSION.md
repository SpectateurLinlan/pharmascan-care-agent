# Submission Control Center — PharmaScan Care (as of 2026-10-13 SGT)

**Competition:** Tencent Cloud AI CAN DO IT Hackathon Singapore 2026 — Healthcare Challenge 2. **Submission target:** Friday, **2026-10-16**, actual *clock time/timezone* must be confirmed from submission form; do not assume midnight. **Grand Final:** 2026-11-03 (top two teams from preliminary evaluation according to supplied summary).

**Requirement interpretation:** the supplied Hackathon brief says video and live URL are optional but have demonstrational/bonus value; user's current portal-oriented list requests video, project link, architecture PPT and source. Treat **all below as target-to-complete**, while **marking formal hard requirements conservatively**. Challenge 2's supplied excerpt does not independently establish that Architecture Diagram PPT is a mandatory challenge-specific upload (Challenge 1 explicitly mentions it). Confirm current submission form before final claim. Do not mark anything submitted until URL/upload receipt verified.

## A. All submission items — placeholders, drafting status and ownership

| Field | Official base / current target | Ready-to-use / placeholder | Status | Responsible |
|---|---|---|---|---|
| **Project Title** | Required | **PharmaScan Care** *(proposed; team to approve)* | drafted—not final | Product/submission |
| **Short Blurb** | Required; **strictly <10 words** | **`A voice-first agent for safer medication routines.`** (7 whitespace-separated words) | drafted—not submitted | Product/submission |
| **Project Description** | Required 4 areas | see Sections B–D below for an editable narrative. Insert actual benchmarks only after tests. | draft | Product + Engineering |
| **Cover Image** | Required; 16:9; recommended 380×216 px | **[TODO]** `assets/cover_16x9.png` (do NOT insert a fake image). Verify aspect 16:9; 380/216 = 1.759 rather than exact 1.778 due to rounding. | missing | UI/design |
| **Project Web Link** | user-specified submission target; original brief 'optional + bonus' | **[TODO]** `https://[deployed-frontend]`, browser-accessible and smoke-tested on phone/desktop with isolated Demo Account | missing | Frontend/Infra |
| **Demo Video Link** | original brief optional; **target complete** | **[TODO]** unlisted/public accessible URL for 5–8 min video (outline below) | missing | Demo/media |
| **WorkBuddy / CodeBuddy conversation history** | Required | **[TODO]** real exported/transcribed chat history in `evidence/workbuddy/`; no simulated transcript | missing | WorkBuddy developer |
| **≥3 actual development chat screenshots** | Required | **[TODO]** screenshots 1 architecture/brief, 2 coding Agent, 3 debug/test; tool UI and real timestamps/context visible; no secrets | missing | WorkBuddy developer |
| **Architecture Diagram PPT** | user-specified target, especially useful to judges; mandatory status for Challenge 2 not confirmed from provided excerpt | **[TODO]** `.pptx` (1–2 slide guide in `ARCHITECTURE.md`) | missing | Engineering/product |
| **Source Code GitHub URL** | required in user's submission list / Challenge source expectations | **[TODO]** actual `https://github.com/.../pharmascan-care-agent` URL; confirm public/private access, no secrets | missing | Repo lead |
| **Social Media Post Link (bonus)** | Optional bonus | **[TODO]** platform URL with **#WorkBuddy #CodeBuddy #Miora #TencentCloudHackathon** as listed. Check whether all tags or selection required in current portal; use all to be safe only if truthful to tool use. | missing | Product/marketing |

> Required **proof of actual WorkBuddy/CodeBuddy use**: the written development report and screenshots cannot be generated retroactively. A compiled PDF of old ChatGPT discussions does **not** satisfy tool-use evidence by itself.

## B. Project Description — editable English draft

### Project Overview: Target Scenarios, Users, and Value Proposition

**PharmaScan Care** is a patient-facing, voice-friendly medication management and longitudinal self-care agent for people independently managing multiple oral medications, with accessibility designed around older adults. Its initial prototype addresses home medication routines, new prescriptions/pharmacy-label instructions, visual confusion between pills, medication-taking records, and preparation for follow-up discussions. Instead of requiring a photograph for every dose, a Smart Check mode supports quick self-report and targeted photo assistance when a medicine is new, changed or uncertain. A consent-linked caregiver contact can receive limited assistance notifications when that capability is implemented.

### Real-World Scenario Insights: Source of Pain Points, Audience, Core Problem

In routine home care, written directions, the actual pills a patient handles, and their history of whether a dose was taken are often managed separately. Confusion may arise when patients use multiple medicines, switch packaging, forget a dose or cannot read fine print. A single classifier cannot resolve the full problem: image similarity may be misleading, dosage instructions may be absent, and recording 'taken' cannot prove ingestion. The prototype is designed to lower the effort of organizing source-based instructions while handling uncertainty responsibly. These pain points are **design hypotheses grounded in the workflow**; a claim of measured prevalence or improved health outcomes requires external evidence/user research.

### Comprehensive Solution Design: Business + Technical Architecture and Prompts

A React TypeScript mobile-first PWA connects through authenticated FastAPI APIs to Supabase PostgreSQL (versioned Medication/Regimen records, patient gallery, dose events, observations and task memory), private Storage and an externally hosted Stage2 visual model built from US NLM C3PI. Label/PDF OCR produces structured **drafts with field-level provenance** that users review. Optional visual references may include mapped US catalogue candidate images and patient-supplied cropped loose-pill images, but neither a model top-ranked candidate nor a copied label becomes an unreviewed prescription. A **single constrained Agent orchestrator** interprets patient intent, reads authorised context, chooses typed tools and asks for missing information. Tool results feed a deterministic evidence and safety layer that limits writes, detects conflicts, separates image resemblance from medication identity and distinguishes self-reported intake from actual ingestion. The system resumes pending tasks across sessions. Tool prompt templates define each tool's input and scope; patient context and untrusted OCR/drug-source text are kept separate from system instructions, and outcomes are logged for testing. No Tencent ADP required; WorkBuddy participates in development. Browser SpeechRecognition and authenticated server-side Tencent TextToVoice form the core demo voice path; physical-device acceptance remains pending.

### Business Value: Measurable Impact, Hypotheses and Feasibility

This project is designed for low-friction, source-linked medication self-management. The main product hypothesis is that personal visual references combined with longitudinal reminders and follow-up provide more meaningful utility than isolated visual pill identification. The initial **go-to-market hypothesis** is direct patient access with potential community pharmacy/home-care B2B2C partnerships; no customer revenue/willingness-to-pay is yet validated. Planned measurable outcomes include held-out Stage2 Top-1/Top-5 retrieval accuracy, personal verification false-acceptance/false-rejection rates, safe rejection in unknown/duplicate-image scenarios, medication onboarding completion, dose event status completeness, agent tool-call scenario success, average user taps and usability/accessibility observations. These are **planned measurements**, not achieved improvements. Prototype runs on synthetic patient data; clinical HSA classification, actual deployment permissions, licensed interaction data and user studies are future steps.

## C. Demo video 5–8 min (recommended 6:30 storyboard)

| Time | Segment | Actual proof to show |
|---|---|---|
| 0:00–0:40 | Pain point and intended user | A fictional patient's crowded medicine shelf and issue of visual confusion, no clinical outcome claims |
| 0:40–1:20 | Product overview & safe boundaries | PWA welcome screen, Try Demo separate user and synthetic baseline, Smart Check |
| 1:20–2:30 | Enrollment → Regimen | Scan pharmacy label or manual source, OCR fields with missing text pending, patient confirmation, active/historical versions |
| 2:30–3:45 | Stage2 + Agent | Daily dose single-pill crop, `/embed` + `/match` true tool trace; difference between resemblance and clinical identity |
| 3:45–4:40 | Failure & recovery | Unmatched / duplicate-box or unprinted blister; alternate evidence request + safe abstention with stored unresolved event |
| 4:40–5:40 | Longitudinal self-care | report taken/unsure, history/health observation, preventive task, healthcare preparation summary |
| 5:40–6:15 | Architecture & test evidence | show Agent tool trace and policy gate plus the app/DB/model split |
| 6:15–6:45 | Build reflection | WorkBuddy's actual contributions: planning, code/test/debug; an issue found and fixed, tips and limitations |
| 6:45–7:00 | Roadmap/close | admit unvalidated model cases and deployment limits; future HSA/market validation |

Adapt timing for a shorter truthful demo. **Do not use mock screen recordings presented as connected real calls.** Label mock/demo data and partial features visibly.

## D. Architecture diagram PPT contents / 2-slide guidance

1. **Slide 1:** top A–D patient lifecycle; middle single Agent Loop (Observe/Plan/Tool/Policy/Adapt/Persist); bottom Vision API, OCR/Knowledge, Regimen & History/DB, Reminders/Voice; cross-link user confirmations. Indicate no ADP/hospital integrations.
2. **Slide 2:** trust boundaries and architecture topology: Patient React PWA → FastAPI authenticated application services + deterministic safety → Supabase Auth/Postgres/Storage + external HF Stage2; WorkBuddy *build-time only*. Label input validation, source provenance, 'visual candidate not clinical identity', approval, privacy boundary, audit and model versioning. Details in `ARCHITECTURE.md`.

## E. Required submission QA (do on 10/15–16)

- [ ] Project title approved by team; blurb **<10 words** checked twice.
- [ ] Draft description replaced any claims of 'implemented' that have no actual tests; real numbers supported by evidence and dataset/split.
- [ ] Cover is 16:9, opens and meets uploader size constraints.
- [ ] Web link opens in incognito/mobile with working Try Demo, isolated data, no secrets, clear labels.
- [ ] Video 5–8 min if submitted, link plays without sign-in and reflects actual build.
- [ ] At least **three genuine WorkBuddy** chat screenshots, full conversation evidence, dates/task changes, no screenshot redactions that obscure proof.
- [ ] Architecture PPT has both component-level and trust-boundary detail; labels current vs future features.
- [ ] GitHub link accessible to organisers and includes README, setup, licensing info, attributions and no credentials/real medical data.
- [ ] Optional social link includes requested tags and truthful claims.
- [ ] Final form submission receipt / confirmation screenshot stored by submission owner; don't wait until unspecified last hour.


## Current local submission freeze (2026-10-14 SGT)

Narrative above includes roadmap items. Current implemented evidence: verified anonymous Auth/user-JWT RLS, reviewed manual enrollment with immutable submitted label extraction evidence, scheduled/PRN reports with independent atomic confirmation, history, source preview using real Stage2 read-label, browser speech adapter/editable transcript and real Tencent TTS playback wiring. Current Agent uses REAL verified Gemini function calling with deterministic safety/grounding and a disclosed rules fallback (see the personalised runtime update).

Do not record the video as if camera/personal-gallery matching, automatic prescription/PDF OCR, clinical recognition accuracy, automated longitudinal care tasks, caregiver delivery, SMS or closed-browser reminder delivery were working. Personal reference eligibility has local policy tests; runtime gallery integration remains partial. Reminder preferences are occurrence-bound in-app records, with no schedule/intake mutation.

Use a truthful demo outline: open private demo -> reviewed enrollment/source preview -> current dose -> browser speech transcript review/edit -> Agent -> separate B14 Confirm -> history -> unsupported/error typed fallback. Physical voice acceptance must precede final recording. Cover image, public deployed link, video link, architecture PPT, genuine qualifying Tencent-tool history and at least three genuine screenshot references remain placeholders requiring human-provided artefacts. Codex browser screenshots are synthetic QA evidence, not WorkBuddy conversation screenshots. No submission/publication/deployment was performed.

## Manual acceptance repair disclosure

Supersedes the earlier submission-freeze verdict: Session03 and deployment remain NOT READY until the reported browser defects are manually reverified on current backend8001. Automated same-user create/resume/review/activate/reload, tonight/uncertainty/B14 and safe Stage2 photo evidence are being rechecked. Do not describe runtime personal-gallery matching as complete. Upstream API now announces0.9; frozen0.8-compatible read-only evidence is used, not new Stage2 features. Mandarin browser/TTS acceptance and human submission/deployment artefacts are still required. No Tencent ASR invocation or new paid TTS verification is performed during this repair.


Personalised runtime update supersedes older manual-repair status: Gemini Interactions/function-call/application/Auth/RLS/B14 and Chinese response have real API verification; Chinese Tencent TTS is real200/WAV. Course dates/preferences/session/quota are persisted. Video must still wait for human physical English/Chinese speech acceptance. Personal-gallery comparison/closed-browser reminders remain partial; qualifying screenshots/cover/video/hosting/PPT/licence are human-owned, not fabricated.

## Second patient experience evidence update

Health observations and deterministic week/month/course summaries now have real same-user persistence and generated-at/date-window coverage. Film only the actual reviewed plans, patient reports and feelings, not clinical adherence/causality claims. Medicines and Me use independent task pages; self-report uses an independent two-action confirmation sheet. New screenshot artefacts under local outputs/ are genuine automated Chrome UI captures of synthetic data, not qualifying WorkBuddy chat evidence. Caregiver management, persistent personal gallery/matching, closed-browser notifications and physical voice/email acceptance remain partial/pending. No new paid provider call or deployment/submission was performed.
