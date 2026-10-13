# PharmaScan Care — Product, Hackathon & Evaluation Master Specification

**Revision:** 2026-10-13 SGT · **Decision owner:** PharmaScan team · **Deadline:** 2026-10-16. This is the canonical product and competition requirements document. Sources: user-provided 144-page project synthesis, earlier workflow HTML and WORKFLOW_SPEC, supplied Claude medication lifecycle HTML, and the original Hackathon requirement screenshots in the conversation. Proposed changes are identified as **design** rather than implemented facts.

## 1. Competition identity / non-negotiables

- **Organizer:** Tencent Cloud with AI Singapore. **Track:** NTU LKCMedicine Healthcare. Choose **one** challenge: Challenge **2** *AI Healthier Every Day: Intelligent Support for Long-Term Self-Care*.
- **Must be original and actually built with at least one** WorkBuddy or CodeBuddy product. Preserve real conversations and **≥3 screenshots** of chat logs during development, not fabricated post-hoc. Without proof of use, project may not proceed to scoring per supplied brief.
- **Submission:** Project title, short blurb **strictly fewer than 10 words**, 4-part description, cover 16:9 (recommended 380×216 px), Tencent development chat history/screenshots, source code GitHub URL. The submission portal described by the user also requests a browser-accessible project link, 5–8-minute video, architecture diagram PPT and optional bonus social link. See `SUBMISSION.md` for distinction between baseline required/optional and **our target**.
- **Judging:** ten dimensions, 10 pts each, 100 total: Impact & Relevance; Human-Centered Design; AI Interaction; Technical Execution; Feasibility; Demo & Storytelling; Innovation & Creativity; UX & Accessibility; Responsible AI & Ethics; Overall Quality & Judge's Impression. No separate verified 100-point breakdown for Challenge 2.

## 2. Selected product definition

**Team:** PharmaScan. **Agent:** proposed *PharmaScan Care*. **Proposed positioning:** A voice-friendly, patient-facing medication management and longitudinal self-care companion that helps patients organise source-based regimens, check whether a loose pill visually resembles an enrolled reference, track self-reported adherence and prepare for review.

### Target scenario / Users / Payer / Intended use

- **Primary scenario:** independently living adults taking multiple long-term oral solid medications in Singapore; special accessibility for older patients (large text, voice-first but not voice-only). Adults are *initial validation population*, not a permanent declaration that minors can never use it. Do not claim suitability for children until independently validated; guardian/legal consent is future work.
- **Primary actor:** Patient. **Other actors:** consent-linked family caregiver receives opt-in minimal notifications (not an independent portal); pharmacist/doctor exists as **external real-world professional**, optionally referenced in written-source or mock-data flows, never an implemented actor interface.
- **Account:** Mobile-first PWA. Evaluator clicks Try Demo → unique anonymous authenticated user → isolated seed of **synthetic** record/history; presenter has separate stable seeded account. Email/password for team. Singpass/NEHR not integrated; no NRIC collected, do not render live Singpass login.
- **Customer / payer hypotheses:** consumer/family B2C for initial adoption; community pharmacies, home-care and ageing-in-place organizations as B2B2C distribution/paid partnership research hypotheses. **No validated willingness-to-pay, customer agreement or impact claims.** Avoid an elderly-only or nursing-home-only story that forces an unnecessary care-staff portal.
- **Intended use (research prototype wording):** *Assists patients with organisation of recorded medication information, reference-photo comparison, reminders, self-reported medication taking, and communication preparation. It does not independently identify pill composition, establish medication safety, diagnose, prescribe or verify ingestion.* Potential medical-device software (SaMD) regulatory assessment required for real deployment; no HSA class or registration is claimed.
- **Market gap:** Medication schedules and medication appearance are separate pieces of information in patients' daily routine. Existing medication apps/HealthHub may already support lists/refills/reminders. Our differentiator to **validate** is source-linked personal visual references and agent-directed uncertainty recovery, plus multi-day follow-up — not invented claims of competitor deficiency.

## 3. Six Challenge 2 capabilities — observable acceptance, not just headings

| Capability | Feature + evidence required | Priority | Status on 10/13 |
|---|---|---|---|
| Medication understanding | Patient asks about a **confirmed recorded medicine** → knowledge retrieval source with citations, separate original patient dosing; simplified explanation in speech/text | P1 | Designed; not verified |
| Medication management | Manual/label/PDF enrollment → source-preserving medication/product + **versioned active/historical regimen**, dose schedule, start/stop uncertainty, source comparison | P0 | Designed; not verified |
| Adherence support | Due reminder, Smart Check optional photo, self-report `taken/not_taken/unsure`, calendar and barrier clarification; no false claims of actual ingestion | P0 | Designed; not verified |
| Health tracking | Timestamped BP/glucose/symptom or lifestyle observations, 7-day trends, units/provenance, no inferred causality | P1 | Designed; not verified |
| Preventive health | Explicit user-/source-provided screening/vaccination/follow-up/lifestyle task with reminders; **refill alone is not sufficient** | P1 | Designed; not verified |
| Healthcare preparation | Patient-reviewable timeline, unresolved items, questions for doctor/pharmacist; export/share locally without fictional clinician transfer | P1 | Designed; not verified |

## 4. Complete patient narrative (borrow the strength of Claude lifecycle)

**Phase A — Create/Update medication plan.** Patient uploads a dated pharmacy label or prescription, or enters data manually; optional mock hospital FHIR-like fixture demonstrates future source interoperability but is not an actual EHR connection. For supported readable medicine-box/pharmacy-label images, the app first uses the PharmaScan `/v1/read-label` provider. For prescription/PDF inputs that are not supported by that provider, use the document-extraction fallback or manual review. Source extraction may suggest only fields **explicitly present** in the source (name, ingredient, strength, form, dose, frequency, route, timing, PRN, duration, start/stop). Agent compares with existing active/historical regimens, asks exactly what is missing, flags duplicate ingredients / potential DDI with coverage, requires the patient to review against the original written instructions. Do not infer a 15-day course from 30 pills × 2/day.

**Phase B — Prepare Personal Gallery.** This is **not** merely a set of classifications. Record product identity separately from (1) `catalogue_seeded_candidate` (US C3PI reference for a *mapped* product, model encoder compatibility/licence unverified) (2) patient-supplied loose-pill reference (optional 3–5 per side, only if convenient, no forced early deblistering), and (3) packaging/label/blister photos (private storage, not directly included in loose-pill 256-d matching). A candidate is **not verified identity**. Model upgrades require versioned re-embedding from consented stored originals.

**Phase C — Everyday support.** Default **Smart Check**: reminder → [Taken] [Check pill] [Not now] [I'm not sure]. No mandatory photo every dose. If patient requests photo, route by modality: one loose pill (cropped, image quality → Stage2 gallery match → optional catalogue lookup), printed package / pharmacy label (`/v1/read-label` through `SourceExtractionPort`), unprinted clear/opaque blister (request packaging/source; do not identify blindly). Compare current regimen and previously logged events through deterministic gate. Speak concise result; ask after action what actually happened. Preserve two axes `vision_status` and `intake_status`. Abnormal branch asks guided retake if blur/glare/too-small (if actually measured); high quality but no match → uncertainty/possibly unregistered medication **without guessing**. Existing `/scan` duplicate boxes are not dose-count evidence.

**Phase D — Regimen transitions + longitudinal care.** Medicine stopped/changed → close historical regimen, keep product/history/reference and prevent use as active reference; new start or dosage adjustment = new version with source. Agent later asks about missing reports, symptoms and adherence barriers; records timestamps and reviews relevant patient-provided preventive tasks; produces a pharmacist/clinician question list. No claim that a doctor received it. A DDI change alerts the **patient**, with opt-in caregiver support; professional consultation is external to app.

## 5. Agent proof: beyond a fixed 4-stage model pipeline

**Main loop:** OBSERVE user/event → AUTHORIZE & READ context → PLAN tool or question → EXECUTE typed tools → VALIDATE deterministic policy → either ADAPT (re-photo / OCR / ask for prior source / abstain) or REQUEST confirmation → ACT via safe service → PERSIST state/tool traces → SCHEDULE follow-up.

- *Relevance-driven routing:* an uploaded photo can mean dose check, add medication, or unknown pill; if ambiguous ask with two numbered options. An agent can skip Stage1-4 entirely for adherence summaries and no-photo self-report.
- *Tool feedback:* if `/scan` yields two overlapping boxes for one pill, reject dose-count evidence; suggest single-pill crop. If catalogue candidates are low-coverage, do not overwrite `product_id`. If user says missed-dose/unsure, read history first, never recommend compensatory dosing.
- *Cross-session state:* pending user clarification, scheduled tasks, unsolved match and patient preferences survive reload, with audit and idempotent actions.
- *Critical boundary:* agent reasoning governs task selection and patient-facing explanation; deterministic validation governs permissions and medication-management state. A fixed subworkflow can legitimately exist inside an Agent.
- *Proof required:* real tool-call trace with name/args (redacted)/result/state transition, a failing/uncertain branch and a successful safe recovery, not a hard-coded four-answer script.

## 6. Coverage limitations and uncertainty wording

- NLM C3PI is a **US pill image catalogue**. No asserted coverage of Singapore products, OTC/supplements, China, extended-release vs IR, all brands or packaging. Similarity is not probability, and visually indistinguishable tablets cannot be differentiated using an image alone.
- Box labels/medicine bag instructions may include dose/frequency/duration, but fields vary. Doctor instruction may have changed since printing; select latest reviewed record and retain provenance.
- `confirmed_match` is an unsafe label for image-only output; prefer `visually_consistent`, `ambiguous`, `unmatched`, `image_unusable`, `not_checked` with evaluation version.
- Lack of image quality metrics cannot produce a precise photographic explanation. Agent may say 'I cannot reliably assess this photo' instead of hallucinating 'too dark'.
- DDInter claims require mapping, source licence, medical context and coverage; negative result does not prove safety. No automated new/stop/adjust medication plan based on DDI.
- Historical gallery remains stored (within retention policy), but should not be considered current active medication for dose checks.

## 7. Predefined demonstrable stories (synthetic only)

1. **New label & medication update** → OCR extracts limited fields → asks for missing dose schedule → user reviews source → versioned active regimen; optional reference image.
2. **Normal scheduled dose** → user chooses Check pill → real Stage2 embedding + patient gallery visual candidate → backend gate → short voice/text explanation → user self-report event.
3. **Wrong/unknown photo** → photo may be clear yet mismatched; avoid false certainty, offer recapture/imprint/source check, record unresolved state.
4. **Existing Stage1 failure** → one TEVA pill produces two overlapping boxes in `/scan` (as screenshot observed); gate rejects count, suggests one-pill controlled crop; regression test.
5. **Unprinted blister** → no OCR text and loose-pill encoder not validated for intact packaging; ask for outer box/label, no forced removal.
6. **Week-later follow-up** → missing confirmations vs true missed doses distinguished; collect patient reason and health observations → patient-reviewed care summary, preventive task and clinician discussion list.

## 8. Quantifiable evidence plan — no fabricated impact

| Outcome | Experiment or metric | Source & claims boundary |
|---|---|---|
| Visual retrieval | Top1/Top5 on held-out labelled US C3PI; per-class confusion | Do not conflate training accuracy with deployed benchmark or clinical identity |
| Personal verification | Genuine vs impostor pair split by physical pill/photo session, False Acceptance Rate (FAR), False Rejection Rate (FRR), unknown reject/ambiguous | Calibrate thresholds and confidence without leakage; different strength lookalikes |
| Detector reliability | 1→1 pill box regression; IoU/NMS; multi-pill count MAE; background/lighting robustness | Count is untrusted until tested |
| Agent quality | Tool success %, branch/state correctness, clinical safety invariant pass %, recovery from timeout, state persistence | Save true traces and scenarios |
| User experience | Five-scenario task completion, number of taps, time-to-log, larger text and voice fallback | Synthetic/internal pilot is **not** a usability clinical study |
| Longitudinal data | completeness: taken/not taken/unsure/not recorded; patient-generated summary completeness | No claim of improved actual adherence or reduced adverse events |
| Business | Cost per simulated active user, willingness-to-pay discovery, potential staff review time (future study) | Hypotheses, not proven ROI |

## 9. Explicit exclusions

No doctor portal, no hospital integration, no real Singpass, no collection of NRIC, no authenticated clinical diagnosis, no pharmacy order/refill automation, no real-world DDI-based dose changes, no multi-agent system, no wearable dependency, no always-on camera, no new unprinted-blister classifier, no Stage2 dual-head/retraining before submission, no auto-conversion of feedback into labelled training set, no ADP dependency, no unsupported claim of accessibility certification/HSA approval.
