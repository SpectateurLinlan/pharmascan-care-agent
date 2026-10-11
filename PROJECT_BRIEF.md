# PharmaScan Care — Hackathon MVP Project Brief

**Status:** Planning specification, not evidence of implemented functionality  
**Last updated:** 12 October 2026  
**Team:** PharmaScan  
**Proposed agent project name:** PharmaScan Care (subject to team confirmation)  
**Proposed repository:** `pharmascan-care-agent`  
**Competition:** Tencent Cloud AI CAN DO IT Hackathon Singapore 2026  
**Track:** Healthcare — NTU LKCMedicine  
**Selected challenge:** Challenge 2 — *AI Healthier Every Day: Intelligent Support for Long-Term Self-Care*  
**Submission deadline:** 16 October 2026 (confirm exact timezone/cut-off in submission portal)  
**Current status:** Main application and Stage 1 have **not** been built. The team reports an independently hosted Stage 2 pill identification API, but its request/response contract and availability are **not yet verified**.

> **Truthfulness rule:** This document specifies the desired MVP, not what has already been built. Do not claim existing integrations, validated model performance, clinical safety, official HSA classification, or completed features without evidence.

## 1. Vision, users, and commercial hypothesis

**One-liner:** A voice-first companion for medication tracking, visual matching, and care support.

**Problem:** Patients managing ongoing medications can struggle to organise prescription changes, distinguish visually similar pills, remember what they have taken, understand medication information, and communicate questions to caregivers and healthcare professionals.

**Primary user:** A patient managing medications independently at home. The user interface should be accessible to older adults (large text, low cognitive load, spoken responses) without requiring a different account type or restricting the whole application to older adults. For the **clinical verification of this MVP**, focus on synthetic adult long-term oral solid-medication scenarios; do not claim validated paediatric use.

**Secondary actor:** An optional **linked caregiver contact**, created with patient permission and contact verification. This is a notification recipient, **not** a separate portal/login in the MVP. Parents/guardians and dependent-patient profiles are future access-control extensions; do not imply that child-specific dose support has been tested.

**Not MVP actors:** No doctor, pharmacist, hospital administrator, institutional staff, or organisation portal. A healthcare professional is an **external escalation destination**, not a system user.

**Commercial hypothesis (unvalidated):** B2C-ready patient product; potential future B2B2C distribution/partnerships with community pharmacies or home-care service providers. Do not develop institutional interfaces or claim verified willingness to pay.

**Product intended-use draft:** Investigational patient-facing medication information, regimen recording, visual-candidate matching, medication-taking assistance, self-reported dose records, and follow-up preparation. The application must not prescribe, independently alter medication orders/doses, diagnose adverse reactions, certify that medication is safe to take, or confirm actual ingestion. Clinical deployment requires separate regulatory classification and validation.

**Regulatory planning:** Visual matching used to inform medicine-taking decisions may fall under HSA-regulated SaMD/CDSS rules. Use **potential Class B SaMD as a conservative internal planning assumption**, not an official determination or a claim of approval. Final classification depends on the actual intended use, significance of information, clinical situation, and HSA assessment; critical applications can be higher risk. Do not use a disclaimer to circumvent medical-device requirements.

## 2. Competition requirements and judging

### 2.1 Mandatory participation and submission evidence

- Use at least one hackathon-eligible Tencent AI development tool (CodeBuddy / WorkBuddy; verify current handbook wording regarding Miora), and retain genuine development-history evidence.
- Submit the conversation history of the development tool and **at least three genuine screenshots** from CodeBuddy, WorkBuddy, or Miora conversations. Screenshots should show significant use, such as architecture planning, code modification, tool integration, debugging, and tests.
- Project title; **short blurb under 10 words** as specified in the provided handbook; project description with user context, problem, architecture, prompts/AI interactions, and impact/metrics.
- Showcase cover image: 16:9 (handbook suggests 380 x 216 px).
- Demo video: handbook marks optional, recommends approximately **5–8 minutes**; prepare one if possible.
- Project/live demo link: handbook marks optional and notes bonus potential.
- Provide reproducible code, architecture, setup notes, synthetic data fixtures and a working demo. The prior discussion included explicit GitHub/architecture requirements for Challenge 1; **do not incorrectly state that those exact challenge-specific items were separately mandated for Challenge 2** without checking the final handbook.
- Use the official submission portal to confirm exact required fields, upload limits, deadline timezone and any additional Healthcare-specific criteria.

### 2.2 General scoring rubric (100 points)

| Dimension | Points |
|---|---:|
| Impact & Relevance | 10 |
| Human-Centered Design | 10 |
| AI Interaction | 10 |
| Technical Execution | 10 |
| Feasibility | 10 |
| Demo & Storytelling | 10 |
| Innovation & Creativity | 10 |
| UX & Accessibility | 10 |
| Responsible AI & Ethics | 10 |
| Overall Quality & Judge's Impression | 10 |

The team must prioritise a working, transparent, testable agent over an accuracy claim or an unverified clinical integration.

### 2.3 Healthcare Challenge 2 coverage

1. **Medication understanding:** source-grounded, patient-friendly explanations of *recorded* medicines (purpose, label directions, general warnings); no new individualised prescription advice.
2. **Medication management:** active and historical medication courses, label/prescription upload, regimen updates and provenance.
3. **Adherence support:** reminders, optional pre-dose visual checking, separate self-reported intake confirmation and missing/uncertain event tracking.
4. **Health tracking:** lightweight patient-reported symptom or measurement check-ins and descriptive trends, not causal diagnosis.
5. **Preventive health:** reminders for preventive/follow-up actions already supplied in a care plan or confirmed by the user; not AI-generated screening prescriptions.
6. **Healthcare preparation:** understandable summaries of medication history and questions for a doctor/pharmacist, reviewed by the patient before sharing.

## 3. Existing assets, dependencies and non-assumptions

### Stage 2 (reported existing)

- Candidate pill recognition based on US NLM C3PI. It yields ranked **visual candidates**, not authoritative medication identity.
- Existing hosted application/API reference: `https://davidpansx-pharmascan-api.hf.space/ui/`.
- **Unverified:** actual HTTP endpoint routes, whether it is Gradio/FastAPI, authentication, input schema, output structure, top-k and score semantics, cold-start latency, rate limits, model version, licence/ownership, uptime, available feature embeddings.
- First task: ask the owning teammate for API/OpenAPI/Gradio docs or working request examples and test it from the development machine. Do **not** invent response fields or assume `/ui/` itself is the inference POST endpoint.
- Related user-provided GitHub URL: `https://github.com/398-21/ultrasound_Model`. Its accessibility and relevance to pill recognition were **not verified** from the current environment (it returns not found to the available GitHub connection). The name suggests a possible unrelated ultrasound project; confirm with its owner. Do not copy it into the new medication app or call it the Stage 2 source without inspection.
- The Stage 2 inference adapter is the initial integration choice. Do not immediately import or retrain an entire independent model repository. Obtain source/weights only if API contract, reliability, embeddings, privacy, licensing, or offline deployment demands it.

### Stage 1

- **Not implemented**. Need a lightweight input-image handling path and eventually detection/cropping for images containing multiple loose pills.
- MVP first fallback: require **one pill clearly centred per image** or allow manual cropping; label multi-pill detection as not implemented until tested. If possible, add a Stage 1 detector later with its own tests and annotations.

### Personal gallery embedding

- **Not yet implemented**. The Stage 2 hosted API may not expose an embedding endpoint. Confirm before promising reuse of the Stage 2 encoder.
- If embeddings cannot be extracted, implement a separate, versioned image-feature encoder for **experimental personal matching**, with validation on independent capture sessions and explicit rejection conditions; do not treat raw cosine similarity as calibrated confidence or verified product identity.

### Data

- Use **synthetic patient and prescription examples only** for the hackathon demo. Use public medication data under reviewed licences; do not upload identifiable patient information to public Hugging Face or other external inference services.
- Singapore NDF can help manual product/source verification but an unrestricted public third-party API or bulk-reuse licence has not been verified. Do not scrape it as a production database.

## 4. MVP user journeys and tool routing

### Journey A — Enrol or update a medicine

Patient submits a prescription PDF, pharmacy label photo, medication box, readable blister foil, or manually enters information. OCR extracts **candidates** for product name, strength, dosage form, and regimen instructions. The app displays evidence sources, unknown fields, and conflicts, requiring the patient to review the original label/prescription. Store product, patient-medication link, regimen version, schedule, and provenance. Past regimens are retained; no inferred end date or diagnosis. Optionally enrol photos of loose pills and packaging without opening medicine merely to collect images.

**Input sufficient for a medication record:** reasonably identified product name and enough details to distinguish its known strength/formulation or an explicitly unresolved draft; original source type and review state. **Input sufficient for timed reminders:** reliably transcribed and reviewed quantity, frequency and any relevant timing/PRN instructions. If missing, retain pending status rather than inventing instructions.

### Journey B — Check a dose

Load current regimen and relevant history. User may upload a loose-pill photo, packaging/label, or pre-enrolled transparent blister. Route:

- **Readable text on box/bag/foil:** OCR -> parse -> compare identity details with recorded product/regimen.
- **Loose pill:** Stage 1 crop (when available) -> personal reference matching (if validated) and/or Stage 2 US catalogue candidate retrieval -> evidence reconciliation.
- **Unlabelled transparent blister:** optional experimental same-patient blister gallery comparison; plastic reflection, missing imprints and visually identical products must cause abstention when not distinguishable. **Never** treat this as a confirmed identity.
- **Unlabelled opaque blister:** cannot visually identify a concealed pill. Request its original package/label or professional verification.

Safety: a visual match does not mean the medicine is prescribed, current, due or safe for the patient. Compare with **active regimen** and any prior dose event; reject contradictory information and direct users to inspect their label/pharmacist. An unknown is not force-classified. Do not prompt medication to be taken when evidence is insufficient.

The camera records **visual presentation**, not swallowing. After any optional pre-dose check, ask whether the patient actually took the medicine. Store visual-evidence state separately from `patient_reported_taken / not_taken / unsure`. Never say ingestion is independently confirmed.

### Journey C — Identify an unknown pill

Run standalone Stage 2 candidate lookup on a suitable loose-pill image. Display ranked possibilities with uncertainty, not definitive identification; no instruction to consume a pill without independent reliable information. For unknown/illegible blister material, abstain and request original packaging or pharmacist support.

### Journey D — Longitudinal support

Review self-reported dose history and missing/unconfirmed records; record symptoms or measurements without diagnosing medication causality; present source-supported medication education; schedule documented follow-up/preventive tasks; prepare an editable doctor/pharmacist discussion summary; optionally send limited notifications to a verified, patient-authorised caregiver contact.

## 5. Interfaces and actors

**One login interface:** Patient web app/PWA with voice-first (opt-in/controllable), text and photo inputs, accessible font sizes, large tap targets and clarification choices. Screens: Home/Agent chat, My Medications, Enrol/Update, Dose Check, History, Health Check-in, Care Preparation, Settings/Caregiver contacts.

**Caregiver:** External linked contact only, not a separately authenticated MVP dashboard. Limit any messages to patient-approved notification type/content. Identity/ownership and consent must be checked before sending sensitive details. A full caregiver account, guardian-managed child profiles and organisational staff roles are post-MVP extensions.

**Not built:** Doctor Portal, pharmacist portal, hospital/NEHR/FHIR integration, organisation admin interface, real billing, prescribing or clinical administration records.

## 6. Architecture and storage

Preferred stack for MVP (adjust only after technical feasibility check):

- React + TypeScript PWA client.
- FastAPI Python backend, a **single** stateful tool-calling Agent orchestrator, and a deterministic policy/safety layer outside LLM decision freedom.
- Supabase Auth + PostgreSQL for structured data, Row-Level Security, private Storage for documents/images, pgvector **only if validated embeddings are available**.
- Remote Stage 2 API accessed through `stage2_adapter` with a verified request/response contract, bounded timeouts, clear network/offline errors, model/endpoint metadata, and no invented success results.
- OCR tool for readable packaging and PDFs. Avoid training a new packaging classifier in this hackathon.
- Stage 1 segmentation/detection is a separate work item; single-pill manual framing is the honest fallback.
- Explicit tool-call logs, source references, recognition results, user confirmations and audit events.

### Minimal database entities and relationships

- `patient_profiles` -> optional `caregiver_contacts` and `source_documents`.
- `medication_products` -> `product_ingredients`; `patient_medications` joins patient and product identity.
- `medication_regimens` (versioned) -> `dose_schedule_rules` -> `dose_occurrences`; `dose_events` record self-reported outcomes.
- `visual_reference_sets` -> `medication_images` (image type: `loose_pill_front`, `loose_pill_back`, `clear_blister`, `opaque_blister`, `box`, `label`, `package_other`); `image_embeddings` optional, each with model/preprocess version and correct vector dimension.
- `recognition_runs` stores image modality, adapter/model version, candidate classes/scores, match type, quality flags, uncertainty/conflicts and evidence provenance.
- `health_observations`, `care_tasks`, `notifications`, `agent_sessions`, `agent_tool_calls`, `audit_events` are added for the complete Challenge 2 workflow.

**Constraints:** UUID PKs; proper FKs and patient-ownership enforcement; unique identifiers only when truly unique (same drug name is not enough); versioned regimens; idempotent event/notification writes; time zone-safe schedules; verified provenance; private files; no hardcoded credentials; soft archival rather than silent history destruction; explicit expired/discontinued status; no cross-model embedding comparisons without compatibility.

**Blister-specific schema decisions:** store `image_type`, `visual_reference_sets.reference_type`, `packaging_variant` (nullable), `reference_verification_status`, `source_document_id`, `recognition_method` (`ocr`, `personal_blister_similarity`, `personal_pill_similarity`, `stage2_catalogue`, etc.), `image_quality_flags`, `model_version`, `unverified_reason`. Do not add a separate blister product-identity database or trust image similarity as medication ground truth.

## 7. Agent tool contracts (proposed, not implemented)

| Tool | Role / requirements |
|---|---|
| `parse_medication_document` | OCR/parse with source spans and unknown values |
| `find_medication_product` | Product candidates based on verified product identifiers/text; no false certainty |
| `create_medication_draft` / `confirm_regimen` | Patient review and authorised persistent change |
| `get_active_regimens` / `get_dose_history` | Retrieve current/historical instructions and state |
| `classify_image_input` | Ask user to choose package, clear blister or loose pill when ambiguous; use heuristic/UI first |
| `read_packaging_text` | Extract printed evidence from readable box/bag/foil; unknown on unmarked blister |
| `detect_and_crop_pills` | Stage 1 when implemented; explicit single-pill crop fallback |
| `search_stage2_catalogue` | Adapter to existing remote model; candidates only, verified API contract needed |
| `match_personal_pill_gallery` | Experimental personal image similarity after embedding evaluation |
| `match_personal_blister_gallery` | Experimental, reference-linked matching; no confirmed identity claim |
| `evaluate_match_evidence` | Deterministic reconciliation with current regimen and contradictions |
| `record_dose_event` | Separate visual verification and patient-reported intake, idempotent |
| `get_medication_information` | Source-grounded plain-language explanation, with provenance |
| `record_health_observation` / `create_care_task` | Low-risk journaling and source-backed follow-up reminders |
| `prepare_medication_review` | Draft patient-readable clinical discussion summary |
| `notify_caregiver` | Consent and verified contact checks; restricted templates |

Only backend-authorised identities can access a patient's data. The model never chooses an arbitrary patient ID. Avoid LLM direct database writes; typed tools and deterministic gates mediate state changes.

## 8. Risk boundaries, uncertainties, and testing

- **Do not say** “safe to take”, “confirmed drug identity”, “guaranteed adherence”, or “confirmed ingestion” from a visual match alone.
- If a photograph is insufficient, ask for a clearer photo or original label and allow abstention; cap retries and escalate appropriately.
- Distinguish `matched_candidate`, `ambiguous`, `mismatch`, `unsupported_input`, `unavailable_service` and `unverified_product`.
- Compare packaging and pill against the reviewed product/regimen; time and dose history can contradict a visual match.
- Users can enter OTC/supplements as self-reported products; do not imply medical endorsement, DDI completeness or safety.
- Do not infer paediatric doses, PRN dosing or missed-dose catch-up guidance.
- Do not turn model predictions into ground-truth training labels, and do not retrain global Stage 2 using private user photos without separate rights/consent and validation.
- Use versioned prompts, tested tools and explicit input/output schemas. Log trace IDs without exposing secrets or personal medical data.

**Evaluation needed, not yet available:** Stage 2 Top-1/Top-5 with product/class coverage and confidence semantics; out-of-catalogue rejection; phone-camera lighting/blur; packaging OCR extraction exactness; personal gallery true/false match separation; evidence conflict test cases; tool selection and workflow task completion; accessibility/usability; end-to-end failure handling. Never invent metrics.

## 9. Build order, acceptance checks and priorities

**P0-A — Bootstrap / audit:** Create empty repo and project skeleton; document design; inspect Stage 2 API live from developer machine and obtain example requests. Do not assume existing Stage 1 or accessible Stage 2 source. Acceptance: repo builds and actual remote API contract is known (or recorded as blocker).

**P0-B — Minimum data loop:** Auth or test-identity scaffold, schema migrations, product/patient medication, manual enrollment, active regimen, dose event. Acceptance: manual enrollment -> schedule -> patient-reported dose -> history with synthetic data.

**P0-C — Visual API and OCR:** Adapter to Stage 2, readable label/packaging OCR, mock-safe fallback for API outage, optional single-pill photo capture. Acceptance: real API returns logged candidate data; outages fail transparently; zero fake classifications.

**P0-D — Agent:** One orchestrator selects tools, asks clarifying questions, handles inconsistent medication and unknown inputs, records evidence and respects permission/safety gates. Acceptance: executed tool traces for normal, mismatch, unknown, discontinued, missed/unsure and unreadable label cases.

**P0-E — Patient UX:** Voice-capable accessible chat UI with text fallback, upload, enrollment review, medications and dose recording. Acceptance: a human can finish the main flows end to end.

**P1 — Challenge completion:** simple health observations, preventive care tasks from confirmed sources, medication education, editable review summary, authorised caregiver notification, history views and short demo.

**Stretch only:** Stage 1 multi-pill segmentation, a measured personal blister image-retrieval experiment, more sophisticated metric learning or pgvector search, real caregiver login, broad drug–drug interaction engine, Chinese drug data, automatic model retraining, doctor portal, NEHR integration, live clinical workflows, continuous glucose/BP device integration.

**Deadline buffer:** Freeze working demo and run tests before 16 October; confirm official cutoff. Do not promise multi-pill or unlabelled blister identification if unimplemented.

## 10. Demo scripts (synthetic evidence only)

1. **Enrollment:** Import synthetic prescription PDF or readable medicine label -> OCR candidates -> user reviews details -> save regimen -> optionally enrol packaged/blister references without removing pills.
2. **Normal dose:** Patient checks a medicine using a single-pill photo or readable packaging -> agent invokes appropriate tools -> compares recorded regimen -> logs *self-reported* taken status, not ingestion confirmation.
3. **Uncertainty/mismatch:** Photo/clear unmarked blister gives unsupported or conflicting results -> agent requests original packaging or pharmacist confirmation -> does not approve taking the unknown item; logs an unresolved event.
4. **Longitudinal care:** Demo historical adherence uncertainty + symptom check-ins -> readable trend and review questions -> source-backed care reminder -> optionally authorised caregiver notification.

An advanced real-world question should trigger actual tool calls rather than a scripted single response. Preserve genuine WorkBuddy conversation and at least three screenshots showing code generation/integration and debugging.

## 11. WorkBuddy onboarding and development evidence

**Create a new GitHub repo**, clone locally (example `D:\Projects\pharmascan-care-agent`), open that exact folder as WorkBuddy working directory. First conversation: read this project brief and the official challenge screenshots/handbook; since there is no app code yet, **audit requirements, external Stage 2 URL, and the planned architecture, not nonexistent local source code**. Ask WorkBuddy to scaffold a minimal codebase only after discussing the design.

Suggested WorkBuddy sequence: (1) Ask: read requirements, Stage 2 constraints, produce scoped audit; (2) Plan: approve DB/API/module plan; (3) Craft: create repo skeleton + minimum manual enrollment flow; (4) Craft: inspect Stage 2 API and OCR adapters; (5) Plan then Craft: implement and test Agent orchestration; (6) Craft: responsive UI and Challenge 2 completion; (7) Craft: regression tests, documentation, genuine evidence.

Models: Prefer a reliable **built-in** WorkBuddy model with proven tool calling (such as a listed stronger coding/reasoning model). Select GPT-6 only if actually available for that WorkBuddy account/model provider; **ChatGPT access does not automatically include GPT-6 API access in WorkBuddy**. Avoid third-party API keys/charges just to chase a label. Keep usage evidence from the eligible Tencent development tool, not from unrelated ChatGPT discussion.

Keep `docs/AI_DEVELOPMENT_LOG.md` accurate: date/time, WorkBuddy model/mode, prompt objective, files changed, commands/tests run, failures, corrections, screenshots, and reproducible commit reference. Never fabricate chat screenshots or outcomes.

## 12. Open blockers requiring verification before implementation claims

1. Remote Stage 2 request/response schema, error behavior and availability; whether image embeddings are exposed.
2. Repository `398-21/ultrasound_Model` access/relevance and ownership. Do **not** blindly clone or merge it.
3. WorkBuddy account's actual visible model menu, credit pricing and ability to access local project directory.
4. OCR provider and licensing, document formats and file size limits; dose-plan confirmation user experience.
5. Exact submission portal fields, deadline timezone, demo link requirements and whether Challenge 2 has additional deliverables beyond the general handbook.

## 13. Official reference / project links

- Competition: https://tch.tencentcloud.com/contest/44
- Reported Stage 2 UI: https://davidpansx-pharmascan-api.hf.space/ui/
- Reported separate repository (unverified): https://github.com/398-21/ultrasound_Model
- HSA medical device guidance: https://www.hsa.gov.sg/medical-devices/guidance-documents/
- NLM C3PI resource: https://data.lhncbc.nlm.nih.gov/public/Pills/index.html

**Document owner:** PharmaScan team. This is a planning artifact to review, implement, and update through genuine repository commits.
