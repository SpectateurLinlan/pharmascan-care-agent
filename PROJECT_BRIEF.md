# PROJECT_BRIEF — PharmaScan Care

**Read `00_START_HERE.md` then `AGENTS.md` and all linked docs BEFORE coding.** This file is a routing index and alignment contract, deliberately not a substitute for full project requirements.

- **Hackathon:** Tencent Cloud AI CAN DO IT Singapore 2026, Healthcare Challenge 2 — *AI Healthier Every Day: Intelligent Support for Long-Term Self-Care*; deadline **2026-10-16**. WorkBuddy/CodeBuddy actual usage evidence is eligibility-critical. `docs/SUBMISSION.md`.
- **Team / product:** PharmaScan / proposed PharmaScan Care — a patient-facing, voice-friendly, mobile-first personal medication and longitudinal self-care agent; initial Singapore use case, with an **American-pill C3PI visual catalogue** that is *not* representative of all Singapore medications.
- **Patient goal:** translate supplied prescription/pharmacy-label sources into a reviewed, versioned regimen; optionally build patient pill/package references; assist with (not clinically certify) pill appearance checks; remember user-reported intake; support adherence barriers, health observations, relevant existing preventive/care tasks and clinician/pharmacist review preparation.
- **Actors:** Patient; optional authorised caregiver contact (notifications only); simulated prescribing clinician/source for test fixtures **without real integration**, no separate Doctor/Caregiver portal.
- **MVP safety:** no diagnosis, prescribing, dosage change, skip/redose recommendations, confirmed pill identity/ingestion, real medication decision based on visual similarity, real HSA approval claim. Explicit source, unknown and ambiguity states; deterministically enforce protected write operations.
- **Engine:** Single LLM tool-calling Agent with durable task state, typed backend tools, deterministic safety policy, patient-authorised reads and confirmations. Not a fixed four-stage workflow; specialised vision path (detect/crop → embed/match or catalogue) is one agent tool chain.
- **Already available:** separately hosted PharmaScan Stage 2 service; model owner's response schemas and evaluation are still a moving contract. `/scan` sample produced duplicate overlapping detections and high but misleading catalogue similarity. The app stores patient gallery; do not presume HF persists it.
- **Cloud/development:** React/TS PWA, FastAPI, Supabase PostgreSQL/Auth/private Storage/pgvector, HF model service, optional Tencent ASR/TTS; Vercel/Railway candidates. Use WorkBuddy to build; **no Tencent ADP** for this MVP. Never claim any deployment is live before verification.
- **Business:** direct self-service patient experience; hypotheses to test include community pharmacy/home-care partnerships (B2B2C) and household paid services (B2C). Payer and willingness-to-pay not yet empirically validated. Potential HSA SaMD evaluation before deployment.
- **Feature details / component responsibilities:** `docs/MASTER_SPEC.md`, `docs/ARCHITECTURE.md`, `docs/WORKFLOWS.md`.
- **API and validation:** `docs/API_CONTRACTS.md`, `docs/SAFETY_AND_EVALUATION.md`.
- **Data model:** `docs/DATA_MODEL.md`.
- **Build priority & nightly safe scope:** `docs/BUILD_PLAN.md`, `prompts/02_OVERNIGHT_BUILD_CRAFT.md`.
- **Submissions:** `docs/SUBMISSION.md` with exact hard limit <10 words for short blurb, 16:9 cover placeholder, link/video/screenshots/architecture/source/social.
- **Software engineering rules:** `AGENTS.md` / `CODEBUDDY.md`; no Vibe Coding, no cross-component internal imports, explicit dependencies, strong contracts/tests, simulated test data only.

**Do not invent missing code, results, success statuses, external API response fields, completed screenshots or integrations. Read repository and run tests first.**
