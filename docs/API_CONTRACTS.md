# External PharmaScan Stage2, Main Backend and Agent Tool Contracts

## Patient message / photo evidence boundary (BUG-01)

`POST /api/agent/messages` keeps `text` as the patient's natural-language input.
An additive optional `photo_context` carries a bounded projection of the existing
image routing, source extraction or visual-check results. It contains no image
bytes, patient/regimen ownership IDs, confirmation tokens or executable actions.
Existing text-only clients need not send it; the response contract is unchanged.

The photo DTO is client-relayed **unverified external data**, not proof of provider
authenticity, patient statements, reviewed identity, dosage or ingestion. The server
marks that trust boundary itself, exposes only read tools on photo turns, and also
rejects non-read tool execution regardless of the model's requested action. The
normal explicit text/confirmation workflow remains available separately.

The existing consented PNG/JPEG routing/source/visual endpoints are unchanged.
Structured evidence is available to the model for the current turn only, outside
`current_input`; it never becomes a user message or verified patient reference.
Future turns must re-read an owned source or request the photo again when needed.
Recent user turns and opt-in history contain the patient's text plus a fixed,
localized photo caption. Assistant replies may show clearly unconfirmed,
patient-readable image clues, not technical JSON or processing instructions.

Limits include at most five products/candidates, bounded strings/printed lines,
finite visual scores and a 24,000-character serialized evidence limit. No partial
JSON truncation or raw image upload is added to the message endpoint.

No database migration or historical record rewrite is part of this change. Deploy
the backward-compatible backend before the new frontend; older backends reject the
new optional field. Older frontends can still submit the legacy mixed text until
upgraded. Existing saved mixed-text records may remain: impact assessment and any
production data correction require separate authorization. Do not regex-strip
patient text or silently migrate existing history as a compatibility workaround.

**Current external integration: v0.10.0.** Canonical snapshot: `docs/external/pharmascan-api-openapi-0.10.0.json`;0.8/0.4 snapshots remain historical. The upgrade's actual field mapping and live synthetic evidence are recorded in [STAGE2_V010_UPGRADE.md](STAGE2_V010_UPGRADE.md). API version and embedding model/space/preprocessing are separate compatibility checks. This long-term-care round does not modify external contracts or invoke Stage2. Earlier design sections remain historical where superseded by current implemented contracts below and the coverage matrix.

## A. Prior external endpoints vs app-level ownership (historical table; see current v0.8.0 section G)

| Route (external)                      | Supported claim from earlier OpenAPI                              | App decision                                                                                                  | Owner / blocker                | Priority |
| ------------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ------------------------------ | -------- |
| `GET /health`                       | Health check                                                      | keep                                                                                                          | vision owner; cold start tests | P0       |
| `POST /v1/embed`                    | cropped pill → 256-d vector                                      | keep; validate dimension & metadata; image via backend                                                        | vision owner; real JSON needed | P0       |
| `POST /v1/match`                    | query vectors + caller-supplied gallery                           | keep Hackathon; app owns persistent refs                                                                      | vision owner + app adapter     | P0       |
| `POST /v1/identify`                 | US catalogue ranked visual matches, optional imprint/shape/colour | keep,**candidate only**                                                                                 | vision owner                   | P0       |
| `POST /v1/scan`                     | convenience multi-pill scan / stand-in finder                     | use**diagnostics** only until tested; known single-pill duplicate boxes                                 | vision owner                   | P0       |
| `GET /v1/pills/search`              | US pill catalogue query                                           | keep if product mapping confirmed                                                                             | vision owner                   | P1       |
| `GET /v1/pills/{pill_id}`           | catalogue product details                                         | keep; market caveat                                                                                           | vision owner                   | P1       |
| `GET /v1/pills/{pill_id}/image/{n}` | catalogue reference images                                        | keep as non-authoritative image; check permitted usage                                                        | vision owner                   | P1       |
| `POST /v1/safety/medications`       | ingredient duplication / advisory DDI                             | adapter now; future safety service boundary; no full-safety claim                                             | app; license check             | P1       |
| `POST /v1/safety/dose`              | compare supplied counts vs schedule                               | legacy diagnostic only;**move authoritative rules to main app service**                                 | app                            | P0       |
| `/v1/safety/label`                  | US labeling lookup                                                | wrap as knowledge retrieval only, source citation                                                             | app                            | P1       |
| `POST /v1/feedback` / delete        | consent feedback flow                                             | keep**out of MVP** or explicit opt-in queue, not gallery persistence                                    | vision owner                   | P2       |
| `GET /v1/model-info`                | **proposed; not confirmed**                                 | expose`embedding_space_id`, weights/preprocess, limits, calibration version                                 | vision owner                   | P0       |
| `POST /v1/detect`                   | **proposed; not confirmed**                                 | optional validated detection + NMS/quality flags                                                              | vision owner                   | P1       |
| `POST /v1/search-by-embedding`      | **proposed; not confirmed**                                 | avoid duplicate inferencing, evaluate after freeze                                                            | vision owner                   | P2       |
| `POST /v1/read-label`                 | readable medicine box / pharmacy-label image                      | integrate existing Stage2 capability for product/label extraction; app owns source review and regimen mapping | vision owner + app adapter     | P1       |

**KEEP external API separate from main application APIs.** Distinguish `GET /v1/pills/{id}` catalogue from `GET /api/patients/me/medications` patient medical records. The user has already sent prior API endpoint proposals to vision owner: changes require a new version + migration announcement, never silent deletion.

## B. Suggested typed adapter DTOs (application facing; NOT claims of exact external JSON)

```python
class EmbedInputDTO:
    image_reference: str       # validated private image/crop ref
    modality: Literal['loose_pill']
    crop_contract: str         # versioned preprocessing requirements

class EmbedResultDTO:
    embedding: list[float]     # checked finite, expected 256 only if actual API verified
    embedding_space_id: str
    model_version: str
    preprocessing_version: str
    normalized: bool | None
    provider_request_id: str | None

class GalleryReferenceDTO:
    reference_set_id: UUID
    patient_medication_id: UUID
    product_id: UUID | None
    embedding_space_id: str
    embeddings: list[list[float]]

class MatchResultDTO:
    decision: Literal['visually_consistent','ambiguous','unmatched','unavailable']
    best_reference_set_id: UUID | None
    score: float | None   # VISUAL similarity, NEVER probability
    margin: float | None
    threshold_version: str | None
    quality_flags: list[str]
    provenance: list[str]

class CatalogueCandidateDTO:
    external_catalogue_id: str
    display_name: str
    brand: str | None
    strength: str | None
    form: str | None
    market: str
    visual_similarity: float | None
    source_dataset: str
```


### `/v1/read-label` responsibility

Current evidence shows a deployed UI path for reading medicine boxes or pharmacy
labels and returning structured medication information such as medicine,
ingredients and RxNorm mapping.

This endpoint MAY be used as the preferred image-label extraction provider.

v0.8.0 now specifies `DocumentFields` with nullable Printed directions, quantity,
dose_form, date and expiry_date. The adapter preserves each value + source line.
The schema does NOT supply structured per-patient dose/frequency/timing/duration,
and no image POST has been tested live. The app must NOT assume reliable fields such as:

- dose quantity;
- frequency;
- explicit administration times;
- PRN instructions;
- duration;
- route;
- food instructions;
- special patient-specific directions.

The main application remains responsible for:

1. storing the source and provenance;
2. distinguishing product identity from regimen instructions;
3. detecting missing regimen fields;
4. asking the patient for the original pharmacy label/prescription or manual
   clarification;
5. requiring patient review before activating a regimen.

`/v1/read-label` must never directly activate or modify a regimen.


**Do not fabricate these fields as if the external API emits them.** Write an `ExternalPharmaScanAdapter` mapping real external JSON to these internal DTOs; absent fields remain unavailable/unknown. `ModelVersionMismatch`, `Timeout`, `UnsupportedModality`, `UpstreamSchemaError` each have explicit error pathways. Request contract should cap image and JSON size and redact patient identifiers from external model calls.

## C. Main FastAPI user-facing APIs (to implement)

| Route                                         | Input → Output                                                                     | Side-effect/policy                                        |
| --------------------------------------------- | ----------------------------------------------------------------------------------- | --------------------------------------------------------- |
| `POST /api/demo/start`                      | authenticated**anonymous** principal → isolated synthetic seed status        | idempotent user-owned seed, rate limit; no shared account |
| `POST /api/agent/messages`                  | text + typed attachment refs + session_id → response/tool trace state              | token verified, bounded steps, safe tool allowlist        |
| `GET /api/me/medications`                   | JWT → patient active/history snapshot                                              | patient-owned RLS                                         |
| `POST /api/medications/drafts`              | source/file/manual fields → pending draft                                          | no plan activation without reviewed required inputs       |
| `POST /api/medications/drafts/{id}/confirm` | reviewed field IDs, origin evidence, explicit confirmation → regimen version       | idempotent, scope and source check; historic preserved    |
| `POST /api/medication-sources/extract`      | medication source document/image → normalized extraction DTO + provenance          | source-extraction façade; routes by source type; never activates a regimen |
| `POST /api/reference-sets`                  | linked product + image modality + reviewed evidence → images + eligible embeddings | never place box/blister in loose-pill vector group        |
| `POST /api/vision/check-dose`               | specific due-dose id + image reference → advisory evidence/quality                 | patient plan check + no auto-take flag                    |
| `POST /api/doses/{occurrence_id}/report`    | taken/not taken/unsure, timestamp, optional vision run → self report event         | idempotent, no ingestion proof                            |
| `GET /api/me/dose-history`                  | date range → state-aware history                                                   | not_reported ≠ missed                                    |
| `POST /api/health-observations`             | measure type/value/unit/observed_at/source → record                                | no diagnosis or medication action                         |
| `GET /api/me/care-tasks`                    | tasks/next dates                                                                    | distinguish user-added vs source-backed                   |
| `POST /api/reviews/summary`                 | selected time range → factual medicine/observation summary                         | requires user review before external sharing              |
| `GET/PUT /api/me/preferences`               | visual mode, language, accessibility, timezone                                      | `SMART` default, per-patient                            |
| `POST /api/me/caregiver-contact`            | email/phone, scope, consent intent → pending contact                               | external notification only after independent verification |

### `/api/medication-sources/extract` responsibility

Main-app source extraction façade. It is the single app-side entry point for
turning a medication source into normalized fields, and it routes by source type:

- readable box / pharmacy-label image
  → PharmaScan `/v1/read-label`
- supported prescription/image source not handled by PharmaScan
  → application document extraction provider
- PDF unsupported by current external provider
  → PDF/OCR fallback or manual review
- extraction unavailable
  → manual enrollment fallback

The endpoint normalizes provider-specific outputs into the application's
`MedicationSourceExtractionDTO`.

It does not activate a regimen.

`POST /api/agent/messages` payload should include `client_turn_id` and `session_id`, to avoid duplicate tool actions under retried requests. Do not let the agent select arbitrary `patient_id`.

## D. Quality output codes (distinct from visual decision)

- `image_unusable` with flags (only measured) `blur`, `glare`, `too_dark`, `pill_too_small`, `crop_cutoff`, `duplicate_boxes`, `overlap`.
- `quality_unknown` if no validated image quality analyzer exists.
- `good_quality_but_unmatched` requires **both** a validated quality check and calibrated gallery decision.
- `ambiguous_candidates` when score margins insufficient.
- `outside_catalogue_coverage` when known US-only catalogue cannot resolve locally marketed drug.
- `upstream_unavailable` for service error; never map to `unmatched`.

## E. Tests and team-owner handoff (priority first)

1. P0 Contract: request one **real** successful and one failed JSON response for `/model-info`, `/detect`, `/embed`, `/match`, `/identify`, `/scan` and `/read-label`, including HTTP status, content-type, API version, timeouts and response size; `model_version`/`embedding_space_id` if available; redact images/patient data. Keep them under `tests/fixtures/stage2/` with source/version. For `/read-label`, additionally record which extracted fields are actually returned, which fields may be null, and whether confidence/provenance is present.
2. P0 Vision: reproduce user TEVA single pill → two overlapping boxes; tests must reject duplicate count. Make sure /scan crop/box/identify logic is observable and not an implicit untestable blob.
3. P0 Embeddings: correct normalization, dimensionality, vector compatibility and threshold/margin on held-out same-product/different-product pairs; explicitly include IR/XR and same-shape different-strength ambiguity.
4. P0 Main App: gallery stored in private database; RLS prevents patient-A reading patient-B; no photo still produces only self-report; provider timeout must not be reported as match.
5. P1 Products: name+ingredient+strength+form+brand+manufacturer+market disambiguation; avoid automatic RxNorm US ↔ Singapore product equivalence.
6. P1 DDI: mapped vs unmapped ingredients and NC licensing; no alert does not mean safe.
7. P2 Feedback: consent and deletion/correction trace; do not use patient-labelled gallery training unless human-reviewed and allowed.

## F. Stage2 owner requested response (can paste to teammate)

> Historical v0.4.0 handoff request retained in Git history. Current request: please provide permitted synthetic/public image request conditions and actual v0.8.0 success/failure POST payloads, especially /embed, /match, /identify, /scan and /read-label. Clarify /v1/tools response shape and type the currently unconstrained ScanPill additions. No server changes are made by the main application team.

## G. Verified v0.8.0 adapter contract (2026-10-13)

Evidence: `outputs/stage2_contract_audit.json` covers all 17 operations and 51 component schemas; `tests/fixtures/stage2/v0_8_0/manifest.json` labels all 12 synthetic payloads **SCHEMA_FIXTURE**, not LIVE. `live_manifest.json` and `outputs/stage2_live_smoke.json` separately record GET timestamps/status/content-type/hashes.

| Endpoint | Frozen response / application handling |
|---|---|
| GET /health | Health: ready + version + component status; live HTTP 200/schema valid |
| GET /v1/model-info | ModelInfo required metadata, calibration/imprint opaque objects; live HTTP 200/schema valid |
| GET /v1/tools | 200 schema remains `{}`; audit only, NEVER populate trusted tool registry from it |
| POST /v1/embed | multipart **image**, not file; embedding + **dim**, model_version, embedding_space_id, preprocess_version, normalized, framed_by, visual evidence; optional imprint_reads and text_reading |
| POST /v1/match | results[], each decision/medication_id/name/**similarity/closest/runner_up/message**; response threshold, margin, model/space, evidence, limits. Requests send both model_version and embedding_space_id |
| POST /v1/detect | boxes are **pixel [x0,y0,x1,y1]**, box_flags, pill_count, count_reliable, flags, found_by; no per-box score declared |
| POST /v1/identify | multipart **images** array (single-photo public Port sends one part), NOT image; top_k schema 1–20, current app deliberately caps at 10. Candidates with similarity, dose_form, strength/ingredients/RxNorm/product metadata; optional conditional confidence not exposed as pill identity |
| POST /v1/scan | nested detection, pills, optional dose/input_check, text_reading, evidence/limits; diagnostics ONLY. ScanPill adds unknown fields without typed decision/candidate definitions; do not map them |
| POST /v1/read-label | candidates name/brand/ingredients/strength/rxcui/rxnorm_name/found_in; fields: DocumentFields; list_check optional; provider source photo/pdf_text/pdf_scan. Schema accepts PDF but current transport only validated PNG/JPEG |
| GET /v1/pills/search, /v1/pills/{pill_id} | SearchResponse/Product; audit only, no new patient flow |
| POST /v1/safety/medications, /v1/safety/dose; GET /v1/safety/label | MedicationsResponse/DoseResponse/LabelResponse; audit only, advisory evidence never substitutes for independent app Safety Gate |
| POST /v1/feedback, DELETE /v1/feedback/{consent_id} | FeedbackStored/FeedbackDeleted; recorded only, NOT invoked/integrated |

**Dimension caveat:** schema types embedding as number[], with no minItems/maxItems enforcing 256. The endpoint description and live ModelInfo declare 256; adapter additionally verifies actual length, dim, finite numeric values and declared normalization (norm tolerance 1e-3 is numeric consistency, NOT a clinical threshold). Missing required metadata fails, never falls back to configured values.

**Public boundary:** `app.contracts.vision.VisionPort` and DTOs; legacy infrastructure/vision_contracts is compatibility re-export only. match accepts one **EmbeddingResult** query with model/space/preprocessing metadata plus GalleryReference metadata; multi-query rejected rather than silently truncating. `HttpStage2VisionProvider` validates frozen OpenAPI before projecting wire fields. Unexpected allowed fields are ignored; required fields and invalid typed fields fail closed. Similarity is raw cosine, NOT probability; threshold/margin are declarations, not independently calibrated metrics; threshold_version remains unknown.

**Source boundary:** `app.contracts.source_extraction.SourceExtractionPort` → `PharmaScanLabelProvider`. Product identity and RegimenEvidence are separate. Preserve every Printed.value/line including dose_form, directions, quantity, date, expiry_date; null and omission both mean missing (explicit null tracked). Quantity is amount dispensed, not per-dose quantity; date is not an inferred start/stop date. No parsing printed directions into dose/frequency/times/duration, no direct activation or repositories. `/api/medication-sources/extract` remains a subsequent authenticated integration task; the new Port/provider is not yet wired into the patient HTTP flow.

**Transport:** injected httpx client/config/schema/sleeper, HTTPS/no redirects, bounded response size/timeouts, PNG/JPEG content decode/pixel cap/EXIF stripping. GET network/5xx retries at most two with bounded exponential backoff; POST never auto-retried. 4xx, 5xx/network and malformed/HTML/schema errors are distinct explicit failure types. PDF uses manual fallback until a validated PDF transport exists.

**Live coverage:** GET only, no auth, no patient data or image upload. Image POST, catalogue/knowledge calls and feedback not exercised. Schema conformance does not validate model accuracy, deployed detector fixes, OCR completeness, FAR/FRR or clinical safety; V003 remains incomplete.

## Internal patient auth and self-report boundary (Session 3D)

Persistent business endpoints require `Authorization: Bearer <current user access token>`. `client_id` is ignored for authoritative identity in Supabase mode, including `/api/demo/start`; body/query/agent values cannot choose an owner. Local in-memory demo identity remains explicitly unauthenticated. No raw token appears in domain/application DTOs or error envelopes.

Dose self-report is two-phase: `POST /api/doses/{occurrence_id}/report/challenge` returns a readable medication/version/dose/time/intake summary and challenge; `POST /api/doses/{occurrence_id}/report` submits explicit confirmation with `challenge_id`, `regimen_id`, `intake_status` and a stable `idempotency_key`. Choices map to `reported_taken`, `reported_not_taken`, or `unsure`. The latter write validates owner, purpose, session version, expiry, consumption and report bindings. Reissuing a live challenge reuses its original session/version. Replaying the same report returns the same event; reusing a key for different bindings is refused. `DoseEventRepository.add` may return the persisted DTO to report an atomic concurrent replay.

The infrastructure-only Data API RPC `record_confirmed_self_report(p_event jsonb)` runs SECURITY INVOKER as authenticated. It checks `auth.uid()`, locks the patient's idempotency key, preserves all core trigger/NOT NULL/check/FK safeguards, and atomically inserts the event, consumes the confirmed challenge and closes the occurrence. It never claims proven ingestion. Public helper consumption RPC access is unavailable; the helper lives in nonexposed `pharmascan_private`. Normal business APIs do not expose provider response objects.

Live Data API OpenAPI discovery returned HTTP 401 `Secret API key required` with the available publishable/user credentials. No secret key was requested or used. Implementation was checked against actual migration/schema definitions and real authenticated row/RPC responses. This is a discovery limitation, not a successful OpenAPI capture. Stage2 v0.8.0 is unchanged.

## Session 03 internal integration endpoints

- GET /api/speech/capabilities: configured provider availability, review_required and raw_audio_retained=false; configuration is not proof of account activation.
- POST /api/speech/transcribe: authenticated audio/wav, X-Speech-Consent=true, maximum 960044 bytes/30 seconds; typed editable transcript, confidence=null (provider does not declare a confidence field). Failure returns an explicit error, never a synthetic transcript.
- POST /api/speech/synthesize: authenticated {text, consent}; bounded concise text, PCM WAV response and Cache-Control:no-store. Sanitized provider Error.Code is retained; provider Message, audio and credentials are never logged.
- POST /api/sources/preview: authenticated PNG/JPEG with X-Stage2-Consent=true and X-Demo-Only=true; extraction preview plus review_required, no regimen activation. Unsupported PDF uses manual fallback.
- POST /api/prn/report/challenge and /api/prn/report: same challenge and consent payload semantics as scheduled self-report, occurrence_id absent. PRN rules store NULL time/days per existing database CHECK; PRN events appear in history with event_time.
- GET /api/me/regimens: own versioned regimen view; historical versions do not generate new dose occurrences.

Earlier GET-only Stage2 coverage descriptions are historical: the new synthetic read-label preview POST succeeded REAL LIVE. The external Stage2 v0.8.0 contract remains unchanged. No model accuracy/calibration or live gallery-match claim follows from this result.

## Continuation 2026-10-14: active browser recognition and immutable source evidence

This supersedes the standalone-ASR blocking decision above. Active demo STT uses native SpeechRecognition/webkitSpeechRecognition with feature detection, en-US short utterances, explicit consent, bounded lifecycle and editable review. Browsers may send audio to remote recognition services; this is not guaranteed offline/local-only or clinically reliable. Unsupported/error/denial/no-speech/abort/timeout states preserve typing. No final transcript auto-submits. Tencent SentenceRecognition remains an inactive alternative; its activation mismatch no longer blocks this demo provider choice. Tencent TextToVoice remains server-side.

Home now uses one primary medication card and a compact photo/text/microphone composer. Send is independent of recognition; pending self-report still requires separate Confirm. Audio failure preserves text. Backend source_documents.extraction_evidence (migration006) retains a bounded immutable typed extraction payload, including Printed.value/line and separate product/regimen evidence. The payload is patient-submitted untrusted evidence, not a provider-authenticated prescription. Manual dose/schedule fields remain separately reviewed; source review and activation confirmation remain mandatory. No extraction implies missing dosing fields, safety or ingestion.

PWA manifest provides install metadata only; no offline clinical workflow or reliable closed-browser push claim follows. Physical microphone acceptance remains manual pending until exercised on Chrome/Edge.

### Reminder and active STT contracts

POST /api/reminders {occurrence_id, minutes:1..1440} upserts an authenticated own occurrence preference; GET /api/reminders returns own open/active preferences. Ownership is verified server context; supplied patient_id is forbidden. Agent create_reminder accepts typed occurrence_id/minutes and resolves ownership in the application. Invalid/closed/historical/foreign occurrence is refused. No dose_event is generated.

STT_PROVIDER defaults to browser. The standalone /api/speech/transcribe endpoint is inactive in that configuration; Tencent SentenceRecognition adapter remains available for explicit future configuration. /capabilities now distinguishes active standalone STT from configured TTS. Playing response still uses authenticated /synthesize and ephemeral WAV; browser speech transcript travels through the ordinary /api/agent/messages boundary.

## Manual acceptance repair: internal endpoints

- GET /api/health adds runtime_contract=session03-manual-acceptance-v2 (runtime compatibility, not external-service proof).
- GET /api/medications/drafts/{regimen_id}: own draft/pending state only, same DraftCreateResponse; no activation/write.
- POST /api/agent/messages accepts optional language=en|zh, defaulten; identity never comes from this field or slots.
- POST /api/speech/synthesize accepts optional language=en|zh, defaulten; standard voice selection is server-owned.
- GET /api/reminders adds is_due from server clock; browser polling is presentation refresh only.
- POST /api/visual-check?regimen_id=<optional UUID>: authenticated PNG/JPEG, X-Stage2-Consent=true, X-Demo-Only=true; max8MB/16millionpixels, signature/content validation, EXIF stripped. Selected active regimen must belong to the verified principal. Typed unknown/ambiguous evidence returns comparison_available=false, ingestion_proven=false, safe_to_take_confirmed=false. Provider failure503 preserves recorded instructions/manual fallback; no clinical writes.

Stage2 externalv0.8 contract unchanged. Live upstream announcesv0.9; only proven-compatible read-only detect/identify metadata is accepted explicitly. No personal-gallery/embedding API boundary has been relaxed.


## Implemented personalised internal APIs

GET/PUT /api/me/preferences returns/saves preferred_language(en|zh), derived speech_locale(en-SG|zh-CN), legacy text_size, numeric text_scale_percent (strict integer100..150),voice_enabled,tts_autoplay,reminder_lead_minutes(0..120),timezone and timestamps. Numeric text scale is authoritative; legacy Standard/Large writes map to100/125 and the legacy enum follows the numeric threshold125. PUT rejects identity, provider voice IDs and independently supplied speech locale. Current timezone update supports Asia/Singapore only.

POST /api/demo/start optionally resumes an owned unexpired session_id; foreign/expired references start a fresh own session. POST /api/agent/messages uses the persisted language and accepts the existing session/client-turn fields. Replies disclose mode, optional usage and prepare-only visual_check_request or pending_report. GET /api/agent/usage returns successful llm_user_turns,model_requests,limit,usage_date and next Singapore midnight reset. Counter mutation is not exposed.

Gemini exact allowlist: prepare_health_observation,list_active_medications,check_due_dose,get_dose_status,get_medication_history,prepare_self_report,create_reminder,check_medication_image. Tools reuse application capabilities; prepare_self_report can issue a B14 challenge but cannot confirm or write an event. check_medication_image prepares the owned upload action; the actual image goes through /api/visual-check with explicit consent. Function calls/results preserve matching call_id/name; unknown/malformed/oversized calls/results stop safely.

Draft creation optionally accepts course_start_date/course_end_date (ISO calendar dates). End requires start and cannot precede it. List and activation summary return both bounds. End is inclusive, evaluated in schedule timezone. No end is inferred from medication/product or OCR. Draft ->review ->activation remains required. Uncertainty does not implicitly record taken. Confirm remains the independent patient HTTP action. Frozen Stage2 externalv0.8.0 is unchanged.


### Patient app repair APIs

GET /api/me/medications additionally returns dose_amount,dose_unit,frequency_rule,food_instruction and course bounds from the current reviewed version. Activation summary includes food_instruction. PRN due responses also return dose_description; no scheduled occurrence is invented.

GET /api/reminders/alerts returns owned occurrence/regimen references, medication/dose/food metadata, due_at,remind_at and a presentation deduplication key. The server uses persisted preference lead/timezone and excludes reported/closed doses; future snoozes suppress the original alert. Notification is a review prompt, never intake confirmation.

POST /api/feedback accepts {id:UUID,category:issue|suggestion,message:5..2000 characters}, rejects patient_id/extra fields, returns received status/id/created_at and is retry-safe. Text is stored under verified owner; no external delivery claim.

Email OTP/Magic Link/password endpoints are Supabase Auth identity operations only. Anonymous linking uses updateUser/verifyOtp(email_change); login uses signInWithOtp/verifyOtp(email), or signInWithPassword. Password setup requires verified email. No Singpass endpoint.

## Patient experience revision APIs

GET/PUT /api/me/preferences additionally exposes display_name (1..80 trimmed characters), using the existing profile column. GET /api/me/regimens adds medication_id, reviewed dose/food/course/local-time/is_prn fields for grouped lists and owned details.

GET /api/agent/sessions/{session_id}/recent-turns returns only up to six owned RecentTurn pairs. Unknown/foreign session404. Agent responses may contain health_note_request {description,requires_patient_review:true,urgent_help_advised:boolean}; allowlisted prepare_health_observation has no model parameters, preserves original user input and has no write authority. Final confirmation is the patient's health-note API operation, not a model call.

GET /api/me/health-observations reads at most500 notes in the last366days. PUT accepts {id,occurred_at:timezone-aware,description:1..1000,severity?:mild|moderate|severe,notes?:max1000,medication_id?:UUID,confirmed:true}; owner and timestamps derive server-side. PUT is ID-upsert for retry/edit, rejects foreign medication/future observations and unconfirmed writes. DELETE /api/me/health-observations/{id} only deletes the owned selected note, not clinical history. Body patient_id is forbidden.

GET /api/me/review-summary?period=week|month|course&regimen_id=<course> returns explicit window_start/window_end/generated_at/timezone, actual regimen metadata, stored occurrence counts/without_report, report-time taken/not_taken/unsure counts, bounded observations, review questions and coverage_note. It is read-only, not a clinical adherence or causality score. No stored gallery references or automatic caregiver delivery API is claimed. Frozen Stage2externalv0.8 unchanged.

Current dose history/summary windows return complete stored occurrence/event collections or a provider-unavailable error when exact completeness cannot be verified or the2000record/20page ceiling is exceeded. No silently truncated full counts. Severe/breathing/chest-pain input can return a deterministic conditional help response before any model request, even at app quota capacity; it contains no pending dose/health save.

## Speech cost boundary (2026-10-14)
`GET /api/speech/capabilities` remains authenticated, returns default `provider=browser` and `cloud_tts_allowed` (server availability AND TTS_PROVIDER=tencent). It exposes no credentials. Browser synthesis does not call FastAPI. `POST /api/speech/synthesize` now requires literal `provider=tencent` in addition to text/consent/language. Missing/unknown provider is rejected (422), disabled cloud synthesis is 503 before budget/provider I/O. The persisted preferred language continues to select Tencent's existing English/Mandarin mapping. No Domain/Repository/schema/Stage2 contract change.


## Patient evidence/gallery HTTP boundary (2026-10-15)

Every route requires the existing verified user identity. Business IDs are ownership-checked; patient_id is never a model/request identity selector.

| API | Contract |
|---|---|
| GET /api/evidence/tasks; GET /tasks/{id}; GET /tasks/{id}/sources | Typed bounded tasks, original source records and provenance for explicit resume. |
| POST /api/evidence/tasks/{id}/sources | PNG/JPEG bytes; source_kind package/pharmacy_label/prescription; optional owned medication_id for explicit association; consent + demo headers required. Persist identity before plan. |
| POST /api/evidence/tasks/{id}/review | Strict reviewed RegimenDraftInput; explicit distinct-product/new-course choice. Returns retry-safe draft; activation still uses the existing confirmation endpoint. |
| GET /api/evidence/gallery | Identity-grouped products, all courses, actual photos and eligible count. |
| POST /api/evidence/gallery/{medication_id}/images | Typed image_kind/source_description/reviewed/for_comparison; sanitized consented bytes; atomic eligible DB reference when supported. |
| GET /api/evidence/images/{id} | Authenticated private PNG proxy, Cache-Control:no-store. |
| POST /api/evidence/images/{id}/retire | Owned idempotent logical retirement; never erases source/history or upgrades eligibility. |
| POST /api/evidence/check-dose | Real query embedding + compatible owned references + current-regimen/source reconciliation; stored RecognitionRun, never intake. |

PNG/JPEG MIME/signature/byte/pixel/decompression checks precede provider use; EXIF is removed. Blank/tiny pill images are rejected as unsuitable inputs, not a calibrated clinical quality claim. PDF upload returns explicit unsupported input. Missing source fields remain missing; narrow literal quantity/unit/HH:MM daily proposals require human review and never derive from strength/dispensed quantity. External v0.8.0 contracts are unchanged.

Source GET returns SourceEvidenceView: original extraction/review fields plus recorded_at/provided_by=patient. Source inspection is available from the Gallery product detail, including completed registrations. Explicitly printed finite course duration requires a reviewed matching start/end window. Generic-name/strength suffix formatting is normalized only for textual name comparison; independently conflicting strength/form remains blocking.

Internal Agent tool `check_due_dose` accepts `window=due|today|tonight`; patient identity remains server-supplied. `today` includes future times in the patient's local day; `due` contains only currently due unreported scheduled occurrences. Rows retain business IDs and add medication_name, dose_amount, dose_unit, local_time, food_instruction and intake_status. Same-user application services provide these facts; bilingual deterministic summaries list the actual records instead of only counts. PRN has no fixed schedule. No medication/dose write is introduced, and external Stage2 contracts remain unchanged.

## Private caregiver contacts (migration020)

GET/POST /api/me/caregivers lists/adds patient-owned contact notes; PUT/DELETE /api/me/caregivers/{id} edits/deletes an owned contact. Create takes stable id, name, optional relationship, contact_type=email|phone, contact_value and storage_consent=true. Email is normalized to lowercase, phone requires explicit country code and strips formatting. Retrying an identical id/body returns the same record; conflicting retries or duplicate own contact details are rejected. PUT takes the same editable fields without id. Identity/verification/sharing/notification fields are forbidden inputs. Owner comes only from AuthContext. Unknown/foreign update/delete returns404. All outputs are pending/unverified, sharing=false and notifications=false. Agent tools cannot access/contact these people. No message/invitation/account link or medical-data disclosure results from saving a contact.

## Stage2 0.10.0 upgrade (2026-10-15)

Runtime snapshot: docs/external/pharmascan-api-openapi-0.10.0.json; older snapshots retained. SourcePreview adds optional label_kind, dispensed_by and message; product adds release/release_printed. RegimenEvidence adds instructions(text/line,dose.amount/amount_max/unit,times_per_day,every_hours,as_needed,times_of_day,food,duration,max_per_day), indication, cautions and supplied_quantity. Original printed fields remain. Legacy derived dose/frequency/time/duration placeholders remain null; these are not authoritative regimen values. Missing/new optional properties default unknown.

POST /api/sources/check-input accepts bounded consented synthetic PNG/JPEG under verified AuthContext and returns typed image_type/checked/abstained/suggested_workflow/message. It never executes remote next_tools, creates a regimen or records intake. Existing evidence-task attach/review/activation APIs are retained; review rejects explicit source contradictions, incomplete duration/course bounds and unsupported interval/range activation. Private sources/task JSON retain new fields without a migration. Upstream read-label uses multipart image plus optional medications JSON string from the owned repository, not caller ownership input. See STAGE2_V010_UPGRADE.md for exact external changes/errors and live-vs-synthetic acceptance.

## Reminder/navigation release additions (2026-10-15)

- GET `/api/reminders/plan`: typed occurrence/regimen/rule/due/reminder projection, owner from principal.
- GET `/api/reminders/calendar?days=30`: private text/calendar attachment, maximum31 days/500 events; no fixed PRN/incomplete export; no-store.
- GET `/api/reminders/push/config`: only availability/public VAPID key; disabled by default.
- GET/POST `/api/reminders/push/subscriptions`: list id/enabled only or validate/save endpoint+P256DH/auth; no patient_id argument.
- DELETE `/api/reminders/push/subscriptions/{id}` and POST `/api/reminders/push/unsubscribe`: owner-scoped revocation, including cleanup while provider is disabled.
- PUT preferences adds `reminders_enabled` and validated IANA timezone. Existing rule timezones remain immutable.
- POST `/api/medications/drafts?medication_id=...`: optional same-owner existing identity; exact product name must agree. Creates a separate unreviewed regimen version using the existing review/activation flow.
- POST `/api/medications/{regimen_id}/end` with explicit `confirmed:true`: authenticated, idempotent record-stop, preserves history; not exposed as an LLM tool.
- GET regimen history includes typed frequency_rule for faithfully editing weekday plans.

No external Stage2 contract or Gemini function allowlist changed. Reminder/notification actions never create dose_events. Browser deep links use `#today/#medicines/#records/#me`; legacy `#history` normalizes to Records.

The internal application runtime marker is `patient-ux-reminders-v1` (separate from the unchanged Stage2 API0.10 contract). Photo results use a `#check-result` child route; acquisition/file state survives task Back/Forward. Unknown/missing-reference HTTP fixtures in navigation tests are explicitly MOCK, not new real Stage2 evidence. Account display metadata is optional for greeting; verified business-record access does not depend on that extra metadata read.
## Long-term care public HTTP and model tools (2026-10-16)

All routes require the existing verified patient context. Identity is not a body/model argument. DTOs reject extra fields.

| HTTP | Public DTO / application use case |
|---|---|
| `GET /api/me/inventory/{medication_id}` | `StockStatus`, current ledger estimate + optional printed quantity evidence |
| `POST /api/me/inventory/{medication_id}` | `StockInput`, explicit `confirmed=true`, stable UUID; atomic append then idempotent task reconciliation |
| `GET /api/me/adherence-barriers` / `POST` | `Barrier[]` / patient-confirmed `BarrierInput`; immutable self-reports |
| `GET /api/me/care-tasks?actionable=true` | owned tasks / actionable projection |
| `POST /api/me/care-tasks` | patient-confirmed `CareTaskInput`, medication-related category/date/context |
| `POST /api/me/care-tasks/refresh` | deterministic idempotent supply-task reconciliation, no stock/dose change |
| `POST /api/me/care-tasks/{task_id}` | confirmed `TaskUpdate`, stable change ID + expected version; complete/contact/defer/cancel/history |
| `GET /api/me/medication-review?days=7` or `30` | `MedicationCareReport`; numeric query coercion tested, other windows422 |
| Existing health-observation PUT | adds validated measurement kind/value/secondary BP/unit, retaining old note inputs |

Missing/foreign references fail with existing NOT_FOUND/AUTH_REQUIRED envelopes; unit/idempotency/version/confirmation errors use INVALID_INPUT. Provider failures remain unavailable, not empty stock. Database list adapters verify bounded complete pagination rather than silently truncating a history.

Exact Gemini additions: `get_medication_inventory`, `get_adherence_history`, `get_health_observations`, `get_longitudinal_summary`, `prepare_medication_review`, `get_unresolved_follow_ups`, `prepare_stock_change`, `prepare_adherence_barrier`, `prepare_medication_care_task`, `prepare_care_task_update`, `clarify_medication_care`. The four prepare-change functions return an unconfirmed `care_request: CareReview`; they cannot execute writes. The clarification function accepts only an allowlisted missing-field enum and returns a controlled question, storing a bounded optional `care_clarification` marker separately from dose clarification. No owner/token/confirmed arguments are exposed. The existing four-round budget, stateless Interactions and provider quota remain. Visit preparation requires complete review evidence, with at most one coverage-repair request within that budget. Deterministic summaries ground factual replies. Audit groups are `get_long_term_care` / `prepare_care_action`, with exact function in the HTTP trace payload. Verified server time and patient timezone enter context via injected clock/preferences.

See [LONG_TERM_CARE](LONG_TERM_CARE.md) for source/stock distinctions and review-window semantics. Existing Stage2 v0.10 external contracts are unchanged.

## Session 04.5 public additions

- POST /api/medications/dose-display: authenticated DoseDisplayInput {basis, units_per_dose, dose_unit}; response calculated / not_calculated / conflict with nullable total and explanation. Read-only arithmetic, no dosing authorization.
- DraftCreateRequest optionally accepts dose_basis; retained on its source. Old payloads remain valid and old regimen history is not rewritten. MedicationSummary optionally returns that basis.
- Existing-product drafts validate known identity facts from owned original/historical sources before writing: conflicting strength, formulation or counted-dose form requires explicit source reconciliation. Names alone do not authorize product reuse. Dose display abstains on multiple/negative/ambiguous mass instructions; it never silently selects the first printed count. Request/response DTO shapes remain unchanged.
- GET /api/agent/history?before=<owned-entry-UUID>&limit=1..20: keyset-paginated {entries,next_before}; entries contain id, user_text, assistant_text, created_at, never executable confirmations. Foreign/missing cursor is rejected.
- DELETE /api/agent/history with {confirmed:true}: clears owned saved messages and recent raw chat text, preserving clinical records/task state. Unknown extra fields are rejected.
- Agent response history_saved is nullable: not requested, saved, or storage failure. A history failure does not fabricate success or suppress the actual answer.
- Evidence attachment accepts automatically_routed=false by default. When true, source kind follows the actual read-label label_kind; a check-input printed prediction alone does not establish dispensing authority.

Stage2 v0.10.0 snapshots are unchanged. Existing check-input is consumed through the backend. next_tools is a provider suggestion, never a tool-execution grant. PDF is not newly enabled.
## Medication course conflicts

`POST /api/medications/drafts` and `POST /api/medications/activate` return HTTP 409 with `code=REGIMEN_OVERLAP` when a same-patient active plan for the same normalized medication name or known product ID conflicts with the incoming course. Different medication-row IDs, per-dose amounts or PRN flags do not bypass this guard. Explicitly end an obsolete recorded plan before replacing it; activation does not automatically supersede it. Existing request/response DTOs remain compatible. `replace_active_plan` on evidence review is retained for compatibility but cannot authorize an automatic replacement. Applied migration025 provides the database backstop; see [data model](DATA_MODEL.md#migration-025-conservative-overlapping-plan-restriction).

This response represents the current MVP's conservative storage limitation, not a diagnosis of an incorrect prescription or an instruction to discontinue medication. UI integrations should explain that overlapping PRN/scheduled or different-dose combinations may be legitimate but are unsupported here, preserve the draft/evidence, and offer review/back actions. Do not automatically retire an existing plan or infer which prescription is correct.

During Vite development, an unavailable FastAPI target now returns structured HTTP 503 `PROVIDER_UNAVAILABLE` rather than an empty proxy 500. Run both services using `python scripts/start_dev.py` and check `/api/health` before diagnosing preference or history persistence.

# Worker dispatcher and device diagnostics

The worker-only application `app.transport.dispatcher:create_dispatcher_app` is
not mounted on the patient API. Its fixed `POST /internal/notifications/dispatch`
requires an expiring HMAC signature, fixed input and no browser Origin. Request
process timeout25s, max5 delivery attempts/pass, shared application projection and
database lease/queue. Counts are processed attempts, never device receipts.
See [authentication, deployment and limits](REMINDERS.md#protected-dispatcher-and-device-setup-local-implementation).

Patient JWT routes additionally provide `POST /api/reminders/push/current`
(`PushSubscriptionInput` → owned id/enabled or null) and `POST /api/reminders/push/test`
(`subscription_id`, UUID `request_id` → `DeliveryResult`). The verified principal
is the only ownership source; no caller-specified patient/destination/message.
Config includes optional backward-compatible `test_available`. Expired test
subscriptions are disabled. Diagnostic sends have local cooldown/replay protection
and do not consume medication reminders, create occurrences or record intake.
# Patient feedback integration: image preview and consent

`POST /api/sources/preview` now also accepts `source_kind=prescription` for
PNG/JPEG prescription photos (not PDF). It remains authenticated, size/signature
validated and read-only: no source, image, regimen or dose is persisted by this
application endpoint. Reading and saving are separate patient actions. Saving
uses the existing owned `POST /api/evidence/tasks/{task_id}/sources` interface and
re-extracts the photo; a browser-supplied extraction is never trusted for writes.

`X-Stage2-Consent: true` remains mandatory for image processing. `X-Demo-Only`
describes the caller's synthetic test input and is no longer a requirement for
ordinary consented photos. Patient UI uploads send `false`; synthetic test
fixtures continue to use `true` when appropriate. No private patient identifier
is chosen by the model. The original photo may contain personal information:
it is sent to the recognition provider and, only on explicit save, stored in
patient-owned private storage. This does not promise provider-side zero retention
or automated removal of personal information.

Same-name product review can use differing, nonempty reviewed strength/form/
formulation evidence without a distinct-product checkbox. Missing or identical
metadata still requires linking existing records or better evidence. Existing
activation, source-conflict and migration025 overlap guards remain authoritative;
different product evidence does not authorise overlapping plans.
The legacy `distinct_product_confirmed` field remains accepted for wire
compatibility but cannot override this product-evidence check.
