# PharmaScan Care — Agent Workflows and API Ownership (Hackathon MVP)

> **Scope and status.** Patient-facing conversational medication companion for Healthcare Challenge 2. Accessible voice-first UX, optimized for older users; same patient interface for all supported adults. Guardian-managed profiles can be designed but pediatric visual medication checks are **not validated for clinical use**. Linked caregiver = verified, consent-based contact for limited notices. No doctor portal, institutional back office or live NEHR connection. Stage 2 API is externally hosted and documented in a team-supplied OpenAPI **v0.4.0**, but many actual JSON response shapes and performance claims are **not verified**.
>
> Read the standalone `PharmaScan_Care_Agent_Workflow.html` for six clickable diagrams and an interactive API backlog.

## 1. Single-Agent architecture and responsibility

**Patient** (image/text/voice and approvals) → **Stateful Agent Orchestrator** (understands intent, loads memory, selects tools, asks clarification, plans follow-up) → **Typed Tools** (`get_regimens`, OCR, PharmaScan API, knowledge, reminders, care tasks) → **Deterministic Evidence & Safety Gate** (permissions, verified source, current regimen, identity uncertainty, dose status, duplicates) → **patient response + event log + long-term memory**.

All tools receive patient authorization from the server's authenticated context, not from a patient ID supplied by the LLM. The Agent may read scoped data, ask the user to verify, retrieve and summarize trusted sources, and create pending drafts. It cannot prescribe, determine a safe dosage, make changes to professional instructions, decide pill identity solely from similarity, or claim ingestion.

**Persistent data (owned by main application):** `patient_profiles`, `caregiver_contacts`, `source_documents`, `medication_products`, `product_ingredients`, `patient_medications`, `medication_regimens`, `dose_schedule_rules`, `dose_occurrences`, `visual_reference_sets`, `medication_images`, `image_embeddings`, `recognition_runs`, `dose_events`, `health_observations`, `care_tasks`, `notifications`, `agent_sessions`, `agent_tool_calls`, `audit_events`. Images/PDFs in private object storage; relational records and vectors in PostgreSQL with RLS. A historical regimen is not overwritten on medication change.

**Vision service (owned by Stage 2 team):** `/v1/embed` 256-d pill-photo embedding, `/v1/match` caller-supplied personal gallery, `/v1/identify` US catalogue candidates, and `/v1/scan` an experimental convenience endpoint. Current OpenAPI does **not** prove it stores patient galleries or supports packaging images.

**Rule ownership:** duplicate intake report, active schedule matching, prior dose events, suspected regimen conflict, permissions and caregiver notifications belong to the main backend. Standalone visual similarity cannot be interpreted as medication safety approval.

## 2. User journeys and state transitions

### 2.1 Medication Enrollment / Update

**Intent:** `ADD_MEDICATION` or `UPDATE_REGIMEN`.

1. **Observe.** Patient asks to add a medication or supplies a prescription PDF, a pharmacy label, a printed box/blister, or manual information. No doctor portal or patient-hospital API integration.
2. **Collect minimal evidence.** Record source type, date, image/PDF, extracted or user-entered name, ingredient when known, strength, dosage form. For *active reminders* additionally require patient-reviewed dose quantity, frequency/timing or PRN designation, route and any applicable written special instructions. Start and end dates remain unknown unless provided; diagnosis is not required.
3. **Use tools.** OCR/field extraction for readable images and PDFs. Product lookup against locally permitted information. Do not use Stage 2 to certify an existing prescription's identity; optional loose-pill retrieval may help find a visual candidate after the document source is established.
4. **Detect duplicate/conflicting regimen.** Different strengths, IR/XR, manufacturers, brands, markets and registration codes may be distinct products. Compare *product*, *patient medication*, *active regimen* and *historical regimen* separately. Re-prescription creates a new regimen/version, not a silent override.
5. **Clarify.** If schedule, strength or source is missing, save `pending_clarification` and ask the patient to consult the original label/pharmacist. Do not invent dosing instructions.
6. **Confirm.** Patient checks the extracted values against the document; this is an `user_reviewed_document`, not proof of pharmacist verification.
7. **Screen potential medication issues.** Duplicate ingredients and DDI are **advisory** only when the structured ingredients are mapped and coverage known. Empty alerts never prove safety; record checked/unchecked sets.
8. **Create regimen** when required data are available; record the source, change reason, updated schedule and audit metadata.
9. **Optional visual enrollment.** Store any box/printed blister/clear blister photos as packaging references. For a properly identified, cropped *loose pill*, call `/v1/embed` and save `vector(256)` plus `embedding_space_id/model_version/preprocess_version` (once obtained from real responses). No requirement to remove pills from packaging just to photograph them.
10. **Finish** by scheduling reminders and saving tool traces. `regimen_active` and `personal_pill_gallery_ready` are distinct flags.

Potential path: `ADD → SOURCE → OCR/MANUAL → REVIEW → DE-DUPE → PENDING or VERSIONED REGIMEN → OPTIONAL GALLERY → REMINDERS`.

### 2.2 Daily Dose Check and Intake Event

**Intent:** `CHECK_DOSE`, from reminder or patient voice/text/photo. Photo is optional.

1. Load current patient's active, reviewed regimens and current expected dose/time **before** visual reasoning; also load prior `dose_events`.
2. Ask whether user wants photo assistance. No-photo path records **self-reported** taken/not-taken/unsure; never attach vision `matched` status to that event.
3. If image supplied, classify *input modality and task intent* with user confirmation when unclear: loose pill, printed package/label, transparent unlabeled blister, opaque unlabeled packaging.
4. Loose-pill path: first prefer **one separately photographed pill** or reviewed manual crop. Use a validated detector with boxes for multiple pills only when it passes independent count tests. The existing `/scan` stand-in finder made 2 overlapping boxes for a single sample—do not rely on it for dose count or duplicate-dose decisions.
5. For a usable crop, call `/v1/embed` (same encoder/preprocessing for enrollment and query) then `/v1/match` with the *current patient's* eligible gallery. Query and gallery vectors must share an embedding space. `match` means the appearance resembles an enrolled reference, **not** verified composition/strength.
6. If matched reference is inconclusive, try another picture/imprint or `/v1/identify` for **ranked catalogue candidates**. The returned similarity is **not** a calibrated probability. A candidate must never silently replace the verified product ID.
7. Printed packaging path: OCR + textual product identifiers/strength/dosage-form check. Unprinted blister path: request original label/box or professional verification; visual blister matching is experimental, not a confirmed identity. No need to break seals to take photos.
8. Backend policy reconciles: identity source, picture quality, active/current regimen, expected dose/count, historic taken/unsure events, discontinued treatments, conflicting specifications, and unsupported input. Reject invalid boxes before any pill count checks.
9. Agent gives an evidence-limited explanation and a next step: request clearer photo, check packaging, user confirmation or pharmacist consultation. No “safe to take” clearance. For uncertain/contradictory product do not advise dosing or auto-adjusting treatment.
10. Ask **after the event** whether the patient actually took it. Save `vision_status` (`not_checked/matched/uncertain/mismatch`) separately from `intake_status` (`not_reported/reported_taken/reported_not_taken/unsure`). Use idempotent writes, audit and follow-up state.

### 2.3 Unknown Pill / Unknown Package

Intent `IDENTIFY_UNKNOWN`. Loose pill → `/v1/identify` with optional imprint/shape/colour and front/back, show ranked **possible** US catalogue matches. Printed package → OCR and product lookup with provenance. Unprinted transparent blister → request alternate proof / save `unverified`; opaque unprinted foil cannot provide pill identity. Never change an active regimen, automatically enroll top-1 or tell the patient to take the unknown item. Offer a pending enrollment draft only if another independent source is found.

### 2.4 Longitudinal, Preventive and Care-Preparation Loop

Trigger on scheduled reminders, review task dates, symptom check-ins, and user questions. Use stored regimens, dose events, patient reports and measurements; missing confirmation ≠ definitely missed dose. Ask about practical adherence barriers and patient preferences. Explain medications with a source-backed general knowledge lookup **separate** from patient-specific instructions. Let the user record trends (BP, glucose, symptoms, sleep etc.) without autonomous diagnosis or dose adjustment. In **Preventive Health** handle source-backed screening/vaccination/follow-up/lifestyle tasks; refill alone is not sufficient. Generate a user-reviewable medication timeline, remaining questions and professional-visit preparation. Notifications to a caregiver only if verified and explicitly authorized.

### 2.5 What makes this Agentic AI?

**Observe** user message, image and timing event → **Retrieve memory** → **Plan** next tool or question → **Execute** OCR/vision/data/knowledge tools → **Check evidence & policy** → either **Adapt** (ask another angle, recheck source, defer) or **Confirm & Act** (only authorized database writes) → **Record outcome** and create follow-up tasks. The agent can switch strategies on tool failure and continue across sessions. Safety decisions remain enforced by explicit backend rules.

## 3. Image routing and modality contract

| Image modality | Primary tool | Can enroll reference? | May confirm product identity? |
|---|---|---|---|
| Single *loose pill*, suitable crop | `/v1/embed` + `/v1/match`; optional `/v1/identify` | Yes, **after source verification**, in pill reference set | **No, not by vision alone** |
| Several separate loose pills | Validated detector → crops → per-crop embed/match; optional `/scan` diagnostics | As individual crops after verifying each | No; observed count requires tested detection |
| Printed box / pharmacy label / printed blister | OCR + structured product matcher | Yes, packaging reference images | Structured source helps but still requires checking |
| Transparent *unprinted* blister | Request existing verified package reference; experimental separate image matching | Yes, packaging reference only | No unless independent evidence |
| Opaque *unprinted* foil | Request outer packaging / original prescription / pharmacist | Can store evidence as unverified | No |
| PDF prescription | Document OCR/extraction, user review | Save source document | For written instruction source only; recency/validity not guaranteed |

## 4. Embedding and `/match` contract

OpenAPI says `/v1/embed` produces a **256-dimensional** vector for a cropped pill photo and `/v1/match` requires `{queries: number[][], gallery:[{medication_id,name,embeddings}], model_version?:string}`. Gallery is **sent by the caller**, not a proof it is persisted by Hugging Face. The returned `medication_id` should map to a `reference_set_id` or an eligible `patient_medication_id`, with product identity and active regimen resolved in the local backend. Keep the API adapter translating between internal IDs and external IDs.

Require Stage 2 owner to report model weights version (not only REST service version), embedding space and preprocessing/crop version, L2-normalisation and cosine metric, threshold/margin calibration dataset, ambiguous/mismatch behavior, and actual responses and HTTP errors. Do not mix loose pill vectors with blister/box vectors or mix different encoder releases, even if both vectors are 256-d.

**Near-term choice:** call `/v1/match` for model-owner-calibrated matching; do **not** casually replace its threshold with home-made `sim > 0.90`. Future local exact cosine on 5–50 references is straightforward when the embedding contract and threshold calibration are truly documented.

**Dual head:** a shared backbone with a verification head and catalogue retrieval head is a reasonable **future experiment**, but not a prerequisite for Hackathon; gather true-positive/false-acceptance evidence first. If a future `/v1/search-by-embedding` is implemented, it may avoid repeating model inference but needs consistent index + preprocessing version.

## 5. Existing API concerns (priority)

See `api_review_and_test_plan.md` for the endpoint-by-endpoint matrix and concrete tests. Critical items:

- **P0 detection failure:** one user-provided TEVA pill image yielded two overlapping boxes in `/scan`, causing two *fake per-pill catalogue results*. Count invalid until fixed.
- **P0 misleading similarity:** 0.97–0.99 scores for different catalogue names. Do not claim 97–99% certainty; investigate metrics, crop contamination, imprints and calibration. Retest with known C3PI ground truth labels.
- **P0 empty response schema:** most `200` OpenAPI schemas are `{}`; collect actual `/embed`, `/match`, `/identify`, `/scan`, `/safety/medications`, `/safety/dose` responses and version them as contract tests.
- **P0 missing model metadata:** add `/v1/model-info` (suggested, not currently published) or obtain an equivalent versioned documented response.
- **P0 role boundary:** `/v1/safety/dose` cannot authoritatively check event history without source-of-truth patient state. Move dose policy to main backend; keep endpoint for backward compatibility/testing.
- **P1 medication interactions:** keep advisory screening only for mapped, coverage-checked ingredients. OpenAPI states DDInter 2.0 under CC BY-NC-SA 4.0; don't assume it is licensed for commercial deployment or that “no alerts” means safe.
- **P1 packaging:** build OCR/field extraction locally, never send an unprinted blister blindly to pill encoder; separate `reference_type` for packaging.
- **P2 feedback:** opt-in training is not personal gallery persistence; pharmacist-verified and user-asserted evidence must be distinguishable, retraining isolated from live medical use and auditable.

## 6. Patient input, autonomous actions and permissions

**User required for an active planned regimen:** product identity as shown by an actual document/label; strength and form; dose and frequency/PRN; a patient review of the extracted or manually provided instruction. **Optional:** start/end date if not provided, diagnosis, doctor name, caregiver, package photo, extra loose pill photos, symptoms/measurements. Agent/system may auto-extract text, suggest structured matches, detect duplicate records, create drafts/reminders, log tool calls, and generate contextual summaries. **Not autonomous:** creating dosing instructions without a reliable source, changing prescription, certifying a pill product, verifying ingestion, auto-feeding patient images into global training.

## 7. Five required demonstrable journeys

A. **Enrollment:** prescription/label OCR → review → versioned regimen → optional photo/embedding → reminder.
B. **Daily normal:** single pill → gallery match → source and schedule check → user intake report → event.
C. **Existing scan bug:** single photo → two boxes → independent quality guard rejects count → ask re-crop or one-at-a-time photo → save unresolved rather than fake success.
D. **Unprinted blister:** OCR not applicable → request outer label/source → store reference image only → no false identity claim.
E. **Longitudinal:** missed confirmations → patient clarifies adherence barrier → health check-in → prevention/follow-up care task → medication review summary.

## 8. Challenge 2 mapping

| Capability | Concrete MVP evidence |
|---|---|
| Medication Understanding | Retrieve general information with citations; separate original regimen directions |
| Medication Management | Active/historical regimen, product identity, packaging/gallery sources, enrollment updates |
| Adherence Support | Reminders, self-report with unsure, photo-assisted checking, barriers and follow-up |
| Health Tracking | User-reported symptoms/measurements with time trends, no clinical causal diagnosis |
| Preventive Health | Source-backed screening, vaccination, follow-up and lifestyle reminders (not just refill) |
| Healthcare Preparation | User-reviewable summary of medicine changes, unresolved events, questions for pharmacist/doctor |

## 9. Implementation gates

**P0:** repo/backend & DB; actual PharmaScan adapter; `/scan` single-pill regression gating; minimal source/manual enrollment; gallery + current regimen + one dose event; agent state/trace + uncertainty; one working demo scenario.

**P1:** OCR of prescription/printed packaging, medication education, long-term follow-ups, health observations, preventative tasks, caregiver opt-in notification, broader end-to-end UX and QA.

**P2:** dedicated Stage 1 detector training once verified necessary; unprinted blister encoder/classifier; global continual learning; dual-head retraining; catalogue search by embedding; independent pediatric safety claims; live hospital integration; institution portals.

## 10. Evidence & scope caveats

- Reference Claude Artifact link could not be inspected from the current tool environment; this blueprint is an original offline interactive document based on the user's descriptions.
- A live PharmaScan Space could not be queried from this tool environment. The cited `/scan` failure is from the user's screenshot and table, not an independently reproduced server test.
- API `0.4.0` is a published **service info version**, not necessarily a stable encoder model version.
- Original Hackathon requirements in the attached retrospective notes specify one healthcare challenge, WorkBuddy/CodeBuddy development evidence including three chat screenshots, and six Challenge 2 capabilities; confirm final submission form for any changed requirements.
