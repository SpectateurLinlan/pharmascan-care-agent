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

## Session 3D security regression evidence

`tests/backend/test_supabase_live.py` is REAL LIVE only with `RUN_SUPABASE_LIVE=1`; otherwise skipped, never counted as live verification. It creates two real anonymous Auth sessions with demo_only metadata, uses their tokens through FastAPI and the Data API, and deliberately issues patient table queries without patient_id filters. A/B read/update/delete/ownership-forgery isolation and own-user positive controls prove the RLS boundary independently of repository WHERE predicates. Both private Storage buckets are tested using synthetic text bytes only: owner upload/read/delete and foreign read/overwrite/delete/path forgery refusal.

The live self-report path checks missing/unconfirmed/wrong-purpose challenges, rollback without consumption/event, explicit confirmation, event semantics, RPC replay, binding conflicts and cross-owner RPC refusal. Local confirmation regressions cover expiry, consumed challenge, wrong owner/purpose, stale session, invalid occurrence, repeated challenge, duplicate confirmation and all three patient choices. Provider mocks verify auth denial, timeout, 4xx/5xx/429, malformed JSON and token redaction; mocks are VERIFIED LOCAL with SIMULATED provider I/O.

Append-only demo enrollment/confirmation/dose history and anonymous Auth identities created by live tests are retained. The tests delete only their own disposable sentinel medications and Storage objects through owner tokens. No patient history deletion or privileged cleanup is performed. `reported_taken` means patient reported taking the dose; visual status remains independent and ingestion_proven remains false.

## Session 03 voice and reference safety evidence

ASR text is untrusted patient input. Confidence is unknown, not invented; review/edit and explicit Send precede normal Agent routing. A spoken self-report can prepare only a confirmation challenge, never prove ingestion or bypass consent. Local tests exercise permission denial, transcript review, provider timeout/failure, empty transcript, and independent medication confirmation using SIMULATED I/O. Real Tencent TTS succeeded; ASR activation failed with FailedOperation.UserNotRegistered, so complete voice/microphone/playback is BLOCKED. No physical microphone or audible playback claim is made.

Real synthetic Stage2 source preview is evidence only, with missing dose/time/duration left unset. No automatic clinical schedule inference or catalogue-to-patient-reference promotion occurs. Gallery/camera and clinical model calibration remain unverified.

## Continuation 2026-10-14: active browser recognition and immutable source evidence

This supersedes the standalone-ASR blocking decision above. Active demo STT uses native SpeechRecognition/webkitSpeechRecognition with feature detection, en-US short utterances, explicit consent, bounded lifecycle and editable review. Browsers may send audio to remote recognition services; this is not guaranteed offline/local-only or clinically reliable. Unsupported/error/denial/no-speech/abort/timeout states preserve typing. No final transcript auto-submits. Tencent SentenceRecognition remains an inactive alternative; its activation mismatch no longer blocks this demo provider choice. Tencent TextToVoice remains server-side.

Home now uses one primary medication card and a compact photo/text/microphone composer. Send is independent of recognition; pending self-report still requires separate Confirm. Audio failure preserves text. Backend source_documents.extraction_evidence (migration006) retains a bounded immutable typed extraction payload, including Printed.value/line and separate product/regimen evidence. The payload is patient-submitted untrusted evidence, not a provider-authenticated prescription. Manual dose/schedule fields remain separately reviewed; source review and activation confirmation remain mandatory. No extraction implies missing dosing fields, safety or ingestion.

PWA manifest provides install metadata only; no offline clinical workflow or reliable closed-browser push claim follows. Physical microphone acceptance remains manual pending until exercised on Chrome/Edge.

### Reminder evidence and final voice classifications

REAL LIVE reminder tests verify cross-user no-filter read isolation, forged ownership refusal, cross-user update rejection, snooze uniqueness, unchanged regimen/events, and subsequent I-took-it confirmation. Local UI verifies reminder state works when Notification permission is denied. No future delivery was simulated as successful. Physical microphone and audible speaker acceptance remain MANUAL VERIFICATION PENDING; Chrome automated tests inject SYNTHETIC STT events but use real Auth/application/Tencent TTS and actual HTMLMediaElement.play/stop.

## Manual acceptance safety regression

Future tonight occurrences derive only from reviewed active schedule. Uncertain free-text intake is read-only; no challenge/event is created. Explicit self-report remains independently confirmed and atomic/idempotent. Reminder due state is authoritative server-clock data and cannot change regimen/intake. Visual candidates remain unknown/ambiguous without eligible personal references and do not prove medication identity, dosage safety or ingestion. Upstream0.9 read-only compatibility is explicit and schema-checked; frozen0.8 embedding/gallery guards are unchanged. Mandarin recognition/provider speech remains manual pending; transcription is reviewable and never auto-executes medication actions. Automated synthetic recognition/playback is labelled separately from real provider calls.


## Personalised Agent acceptance boundary

Gemini is conversational orchestration, not a clinical authority. Model tools do not expose patient identity, SQL, regimen mutation or confirmed dose writes. Function schemas are strict; tool/context sizes and rounds are bounded. Application evidence and deterministic rendering ground patient-specific facts. Ambiguous medicine claims require persisted candidate clarification. Spoken/typed uncertainty is read-only. Explicit I took it prepares B14; History remains unchanged until patient Confirm; retries preserve one event.

Course dates require reviewed evidence and do not derive from model guesses. An unspecified end is not interpreted as medical approval for indefinite use. Reminders remain preferences, not regimen changes or proof of intake. Per-user demo quota and provider429 are distinct; failures preserve medication access and release only the current unfinished turn reservation.

REAL provider verification establishes API integration, not medical transcription accuracy or physical-device acceptance. Physical English/Chinese microphone, consent, editable transcript, Send, audible TTS, denial/failure fallback and B14 must be reaccepted by a human. Personal-gallery matching and background notification delivery remain partial/future; no production security/clinical efficacy/HSA approval is claimed.


Reminder dialog/native notification means review scheduled medication, not take a dose, verified ingestion or B14 confirmation. Neither dismiss nor snooze writes a dose_event or changes regimen. Read-label quantity/strength/date/expiry are not personal instructions/course dates. Explicit days+start calculation is calendar arithmetic over patient-reviewed input, not a dosing recommendation.

Email identity switching must not reassign/merge guest medication records. SDK callback credentials are scrubbed from browser URL/history; provider errors are normalized without raw detail. Patient ownership remains server-verified JWT/RLS. Feedback is a bounded private prototype record, not an emergency/clinical channel; warn users not to submit secrets/medical records. Actual mailbox and physical voice acceptance remain separate from mocked SDK/browser tests.

## Health-note and summary safety

A patient can save a health note only after explicit review/confirmation. The Agent's new typed prepare_health_observation offers original words, never model-generated permanent facts or a save. This revision does not add diagnosis, automatic adverse-drug causality, emergency triage or caregiver notification. Severe/urgent symptoms require professional/emergency help rather than relying on a demo health log. Health review detects a small explicit severe/breathing/chest-pain keyword set and provides conditional help information; this is not validated triage. Physical/provider acceptance is still pending. Emergency wording refers to https://www.scdf.gov.sg/home/about-scdf/emergency-medical-services .

B14 UI now uses an independent bottom sheet, with Taken and Confirm record as two separate patient actions. Cancel creates no event; retries retain existing atomic database protections. Health-note editing/deletion has no dose/regimen mutation capability. Summaries explicitly separate saved reports, stored unreported occurrences, PRN reports and feelings; no report is not missed and no note is not symptom absence. Patient export/share is intentional, no automatic medical dispatch.

Serious-symptom notice is now a deterministic pre-tool/pre-quota safeguard in both configured-model and degraded routing, not something left to model tool selection. It creates no challenge, dose event or health note. The small keyword set is not validated triage and can miss or over-trigger; emergency care must not depend on this prototype. Concurrent read-side occurrence generation preserves existing unique/check/owner guards, ignores only duplicate generation keys and validates the stored winner ID. Complete count pagination refuses partial statistics instead of treating them as all records.

## Current voice cost boundary (2026-10-14; supersedes earlier TTS defaults)
Browser STT review/Send and the existing Agent/B14/RLS path are unchanged. Default playback is frontend Browser SpeechSynthesis, not a backend request. Actual language-qualified voices load via getVoices/voiceschanged; localService preference, en-SG/English fallback and zh-SG/zh-CN Mandarin only. Missing/failed voices preserve text and never invoke Tencent. Rate defaults to 0.9x; generation guards cancel old playback on Stop/new turn/navigation/language/provider/autoplay changes.

Optional cloud requires server TTS_PROVIDER=tencent plus existing ENABLE_SPEECH/TENCENT_SPEECH_APPROVED credentials configuration AND explicit session-only patient selection. Request provider=tencent and consent are mandatory; reload restores browser. Default .env.example/.env use TTS_PROVIDER=browser. Browser STT/TTS may use online services, not guaranteed offline. No new billing activation, provider calls or migration. See README Voice cost policy for enablement details.

Chrome/Edge native API presence and injected en/zh playback lifecycle are AUTOMATED/SYNTHETIC. Headless native voice lists were empty. Physical microphone/speaker, actual installed voices, medicine/dose pronunciation, autoplay/Stop/replay and missing-language typed fallback remain MANUAL PENDING before deployment. Historical real Tencent WAV evidence does not verify browser audio.


## Gallery/evidence safety gate (2026-10-15)

Patient-reviewed product association is not independent product authentication. Visual similarity is not probability, safe dosing or ingestion. Actual Stage2 personal match is interpreted with exact model/space/preprocess/dimension compatibility, provider-reported threshold/margin and independent owned current regimen/date/source-conflict checks. Historical/inactive plans and unresolved strength/form discrepancies return conflict. Missing/incompatible references, unknown/ambiguous results and provider timeout abstain. No reference-to-regimen autoactivation and no visual-to-dose-event write exists.

Packaging/blister are privately stored references; no whole-package/blister matcher is claimed. Unlabeled blister cannot establish product identity or prescribed schedule. PDF parser, clinical source authenticity and comprehensive interaction/dose-safety tools are not implemented. Product category unknown remains unknown. Supplements and patient-entered use do not imply professional approval. No patient images are uploaded for training; synthetic fixture integration evidence is not clinical calibration.

Current automated negative coverage includes source conflict/duplicate/missing instructions, foreign-owner access, retired reference, metadata mismatch, unknown/ambiguous score, Stage2 timeout, Storage failure, blank/tiny input and no intake mutations. Existing independent B14/RLS/allowlist regressions continue to run.

## Caregiver contacts, not verified delivery (2026-10-15)

Patients can explicitly store/edit/remove private caregiver contact details after acknowledging permission to store them. This acknowledgement does not prove the recipient's identity, establish caregiver consent, grant record access or enable medical notifications. Typed payloads reject patient identity/verified/notification/sharing flags; database constraints enforce pending+off+off even for direct authenticated Data API requests. There is no sending implementation or model tool. Real A/B tests verify deliberate unfiltered reads, forged ownership, update/delete isolation and rejected status upgrades. Only synthetic names and reserved example.invalid addresses were used. Independent verification/delivery require a separate future consent/access design and human approval before any actual communication.

## 0.10.0 sticker and advisory safety gates (2026-10-15)

Structured OCR is untrusted, including label_kind, RxNorm/list_check and dispensing origin. Product strength is not dose; count is not clock times; date/expiry/supply are not course bounds; indication is not diagnosis. Source type and extracted fields remain separate. Explicit contradictory products/instructions persist conflict and block activation. PRN does not create scheduled occurrences; ranges and interval instructions require clarification/supported review rather than an invented plan. All intake still requires B14.

One synthetic live safety probe returned an identified ingredient for an intentionally unknown input and incomplete coverage. No patient safety endpoint is enabled by this release; all_identified or zero alerts cannot imply comprehensive screening. DDInter2.0 licence is CC BY-NC-SA4.0 with unresolved commercial permission; US openFDA labels are not Singapore personal instructions. No feedback/training endpoint is called. Physical OCR correctness and independent source authentication remain separate acceptance requirements. Detailed evidence: STAGE2_V010_UPGRADE.md.

## Proactive reminder boundaries (2026-10-15)

No clinical timing inference from OCR frequency, meal wording, strength, supply quantity, expiry or dispensing date. Missing clocks require patient review, never an invented 08:00/20:00 or post-meal offset. PRN is not scheduled automatically. Plan replacement preserves prior versions; explicit stop updates the record and future reminder eligibility, not a recommendation to stop medication. Push content is generic/private; clicks re-enter authenticated RLS-protected workflow. Provider acceptance does not prove delivery, observation or ingestion. No native alarm or guaranteed delivery claim. ICS is not live sync. Local/mock send acknowledgements are not WEB PUSH DELIVERY VERIFIED; physical reception and actual calendar clients remain manual gates.
## Long-term care invariants (2026-10-16)

Inventory estimates never claim physical counts; printed supplied quantity never initializes stock, strength never determines tablet count, PRN never implies a daily consumption rate, and unrecorded doses never imply no consumption or a missed dose. Transactions/initial counts and task history are preserved with owner RLS, atomic ledger updates and retry/version guards. A new physical count resets the estimate; compatible reported taken events are only estimation evidence.

Observations/irregular trends are patient reports without diagnosis, targets or causal attribution. Medication-related review/refill/monitoring tasks derive from explicit user context and confirmation; professional plans remain patient-reported. No general vaccine/screening recommendations, dose changes, pharmacy ordering or caregiver delivery tools were added. Prepared Agent actions cannot persist; the shared human review sheet uses a confirmed authenticated request. Existing B14 remains mandatory for actual intake reports.

Evidence classification and repeatable tests: [runtime workflows](WORKFLOWS.md). Shared-queue claim/cancel does not prove notification receipt. Education without a trusted knowledge source stays unavailable; no copyrighted RAG dataset or new paid provider is used.

## Session 04.5 safety delta

Image type is routing evidence only. Unsupported blister cannot enter a loose-pill embedding space. Dispensing label_kind does not verify authenticity/currentness. Dose totals are conservative source-based display arithmetic, never clinical advice, inferred splitting or strength-derived pill counts. Reviewed source basis is immutable.

Saved conversations require explicit opt-in, a200-pair bound,30-day read visibility and patient RLS. The visibility window is not scheduled physical deletion: Supabase cleanup occurs on later append, so inactive accounts can retain older text; explicit Clear removes chat text. History is text-only: old B14 controls are never replayed. Clearing text preserves challenge/task/clinical state. The Assistant overlay does not authorize writes; independent confirmation sheets remain controlled. Same-user request-scoped connection/preference reuse does not weaken verified AuthContext.

Use pytest default offline regression and opt-in tests/backend/test_session045_live.py for owned-history/source-basis isolation. Browser checks use synthetic local persistence and explicitly mocked visual responses where identified. Physical device Push receipt, clinician validation and real calendar import are separate acceptance outcomes.
## Current consented-photo workflow

Ordinary patient photos are supported with explicit image-processing consent;
the application no longer requires callers to label them synthetic. Test fixtures
remain synthetic and labelled as such. Permission is initially off, stored only
for the current owner on the current device, and revocable in Privacy and data.
It is not clinical review, storage consent or authorisation to access another
patient. Reading uses the authenticated read-only preview endpoint; a separate
Save action writes the original photo and medication evidence to private storage.
Provider-side processing may include personal details visible in the photo.
The product does not claim automatic redaction or zero provider retention.
No identity-document fields or new patient data tables are introduced.

The removed distinct-product checkbox is replaced by checks of nonempty product
evidence; legacy confirmation flags cannot override ambiguous identity. Patients
still review their instructions and separately confirm activation/intake. The
existing same-name overlap restriction remains a conservative MVP constraint,
not a medical determination that two prescriptions are incompatible.
