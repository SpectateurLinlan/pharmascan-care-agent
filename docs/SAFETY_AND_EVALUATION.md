# Clinical Safety, Responsible AI, Engineering Validation & Evaluation

## 1. Medical intended-use position (provisional, not legal conclusion)

The patient-facing MVP helps *organise recorded medicines and time-based tasks; compare a pill image with recorded visual references as an aid; record self-reported intake; retrieve sourced general education; and prepare questions for professionals*. It **does not** diagnose, prescribe, independently recommend dosage, clear a patient to take a medicine, identify pill composition with certainty, determine whether ingestion happened, or auto-notify unconnected doctors. Actual claimed purpose/function matters to HSA SaMD classification; no blanket non-medical-device exemption and no predetermined final class. Regulator/clinical assessment and prospective validation are **post-hackathon** requirements for real-world use.

## 2. Risk and evidence policy table

| Case | Input/observation | Allowed agent response | Prohibited action | Automated invariant |
|---|---|---|---|---|
| Normal matched loose pill | active reviewed regimen; adequate photo; gallery similarity evaluated | 'Looks consistent with your enrolled reference' + user intake question | 'safe to take' or certified identity | no `verified_identity=true` set from vision |
| Similar-looking different-strength pill | same imprint/shape or ambiguous catalogue | ask to use original written label/packaging/professional confirmation | infer 500mg vs 850mg from resemblance | `product_id` not changed by vision alone |
| Photo too blurred / duplicates | explicit quality flags or 1→2 overlapping boxes | targeted retake if flag exists, else generic 'cannot check' | hallucinate precise blur/glare; count 2 as true | `count_valid=false` on duplicate boxes |
| Good photo, not matched | calibrated failure, good quality evaluated | explain unregistered/changed appearance POSSIBLE, check labels | assert definitely not user's medicine | preserve `unmatched/unknown` |
| Model / API unavailable | timeout/5xx/schema mismatch | explicit unavailable; manual source review / self-report | silently return 'matched' | provider status != success |
| Regimen lacks schedule | label product recognized, no reviewed dose instructions | save draft and ask for pharmacy label/clear source | infer dose or create active occurrence | `active` blocked without source-reviewed schedule |
| Regimen discontinued | historical visual match | 'listed historically, not active' + check latest directions | resume discontinued drug | active schedule version check |
| Prior dose unclear | `not_reported` or `unsure` | query/clarify, record uncertainty | automatically re-dose or mark missed | missing != missed |
| Potential DDI / duplication | ingredient mapping available and advisory warning | present source-limited potential concern, refer to pharmacist | stop, replace or alter prescription unilaterally | no `update_regimen` from interaction score |
| No DDI alerts | checked coverage partial or complete | 'No alerts in this reference among checked ingredients' only if warranted | assert combination is safe | store coverage + source version |
| Patient wants caregiver notification | unverified contact or missing consent | request verification, limit content | send PHI without consent | `verified && consent_scope` gate |
| Healthcare question | retrieval source lacks result | say no trustworthy information found and advise professional | generate unsourced dosage | knowledge citation required |

**Short contextual UX phrasing**: normal checks should not require user to reread the whole label each time; only abnormal/new evidence requires a source check. Display full disclaimer at onboarding/feature settings; no repetitive, evasive disclaimer after every successful routine photo. Patient still has responsibility to follow current written instructions; the app must not present image-only results as clinical clearance.

## 3. Security/privacy requirements

- Fake demo user and patient record must be independent per evaluator, not a shared editable account. Supabase anonymous Auth still yields `authenticated` role and must use user-owner RLS. Protect against anonymous spam, lifetime/retention and cross-user token mixups.
- All secrets server-side, restrict domains/CORS, CSRF where cookie auth, upload size/type, SSRF/file traversal on remote resource URLs, image EXIF, private object bucket, short signed URL expiry. No unverified URL fetching by Agent and no remote code execution via agent-generated scripts.
- Explicit consent for audio recording/transcription and if transmitting cropped image to hosted HF (only synthetic image in demo). No NRIC collection. Caregiver notifications require contact verification and opt-in; log failure accurately.
- Limit stored patient chat/tool traces to purpose-required summaries, protect from prompt injection; never include private document content in GitHub log/screenshots. Label sources/LLM outputs as untrusted, do not execute embedded commands.
- Source licences: team OpenAPI mentions DDInter 2.0 CC BY-NC-SA 4.0; do not imply commercial licence. Evaluate NLM C3PI terms and use of catalogue images before public redistribution. Reuse only permitted medication knowledge sources with citations.

## 4. Acceptance-test matrix

| ID | Scenario and action | Expected independently verifiable outcome | Priority |
|---|---|---|---|
| AUTH-01 | Anonymous evaluator A seeds synthetic account; evaluator B visits | records completely isolated, no B reads A data | P0 |
| AUTH-02 | JWT absent/forged/expired | rejection; no agent tool or DB read | P0 |
| REG-01 | Manual label enrollment with written name/strength/dose/time | reviewed regimen version + due occurrence | P0 |
| REG-02 | Package contains name/strength but not schedule | pending draft, specific missing question, no active dose check | P0 |
| REG-03 | User changes strength or stops course | prior regimen/version remains in history; no old reminders | P0 |
| REG-04 | `/read-label` identifies the product but returns no patient-specific frequency | product recorded, regimen stays pending; ask for pharmacy label/prescription/manual instruction | P1 |
| IMG-01 | 1 TEVA pill photo triggers two overlapping `/scan` boxes | don't use reported pill count, log quality failure, ask better crop | P0 |
| IMG-02 | `sim=0.99` but candidate is wrong or conflicts | no probability/identity claim or auto-regimen update | P0 |
| IMG-03 | Query vs gallery embedding_space_id mismatch | fail closed and ask re-embed; no cosine | P0 |
| IMG-04 | Provider returns HTML/empty/malformed body | clean error state; no fabricated match | P0 |
| IMG-05 | Unknown/printed/unprinted blister paths | routed to appropriate OCR/vision/abstain; no sealed pill removal requirement | P1 |
| DOSE-01 | User taps Taken without photo | self-report only, `not_checked` visual status | P0 |
| DOSE-02 | Duplicate tap/retry | at most one event per idempotency key | P0 |
| DOSE-03 | User says 'I don't know if I took it' | unsure; no default missed or extra dose advice | P0 |
| AG-01 | Same chat can request known pill, then clarification, then history | real tool trace/context, no hard-coded responses | P0 |
| AG-02 | User sends instructions embedded in OCR/image | Agent doesn't execute those as commands | P0 |
| AG-03 | Agent tries to invoke forbidden tool/write | gateway/policy blocks and logs | P0 |
| DATA-01 | Device/browser timezone + a due 8pm dose | consistent local time and UTC storage | P1 |
| LONG-01 | Health indicator 7-day trend and source-backed follow-up | correct trend/units, no clinical causal conclusion | P1 |
| LONG-02 | Medication review summary of observed events and unresolved concerns | factual, patient-reviewable, no fictional clinician handoff | P1 |
| CARE-01 | Unverified caregiver recipient | notification blocked | P1 |
| REPO-01 | Ruff, Pytest, TS build/typecheck, migration/rollback (when env exists) | commands and actual outputs logged | P0 |

## 5. Stage2 evaluation protocol and known problems

- **Data leakage:** train/validation/test split must avoid same physical pill/session and highly similar duplicate photos crossing folds; document exact split. C3PI reference vs training images use must be clarified. Don't claim independent test accuracy from the interactive TEVA demonstration.
- **Catalogue:** Top1/Top5 and Recall@K using held-out labelled photos; stratify by imprint availability, angle, background, image quality, strengths/brands and off-catalogue.
- **Personal Gallery:** genuine vs impostor pair distributions and FAR at selected FRR, ambiguity coverage and rejection; test whether catalogue-seeded reference works vs personal gallery. Thresholds selected on validation data, tested held-out; report operating point and failure rate; no arbitrary cosine=.9.
- **Detection:** 1 pill → 1 bbox, multi-pill count and NMS; provide exact TEVA bug fixture plus observed wrong candidate ranking. High similarity 0.97–0.99 unrelated candidates must be explained as raw visual similarity, not confidence.
- **Quality:** image-only explanation flags must be computed from explicit image-quality tool; no GPT-created explanations. No packaging-domain generalization claim from loose pill training.

## 6. Scoring/rubric evidence map (10×10; do not invent score forecasts)

| Dimension | Concrete required evidence |
|---|---|
| Impact & Relevance | source-based pain points; user scenario; clear scope and real constraints |
| Human-Centered Design | mobile portrait, older-adult accessibility, Smart Check low burden, consent controls |
| AI Interaction | multi-step tool selection and adaptive clarification traces; memory across sessions |
| Technical Execution | schema+migrations, actual API adapter, tests, end-to-end deployed app |
| Feasibility | independent onboarding; no fictional Singpass/hospital integration; bounded hosting cost; data licensing |
| Demo & Storytelling | coherent multi-day patient case, true successes/uncertainty, visible safety recovery |
| Innovation & Creativity | personalised reference gallery linked to versioned regimens and longitudinal support |
| UX & Accessibility | font contrast/tap targets/voice/text fallback, landscape responsive, 3–5 step practical tasks |
| Responsible AI & Ethics | abstention, no re-dose, provenance, permissions, versioning, false-high-similarity case |
| Overall Quality | integrated patient journey + real WorkBuddy evidence and correctly scoped limitations |
