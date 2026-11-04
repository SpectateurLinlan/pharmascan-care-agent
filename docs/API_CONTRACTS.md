# External PharmaScan Stage2, Main Backend and Agent Tool Contracts

## Contract authority

The implemented patient API is defined by typed route request/response models in
[transport routes](../backend/app/transport/routes) and [contracts](../backend/app/contracts).
The sections below explain those boundaries; earlier proposed endpoint/DTO tables and
0.4/0.8 handoff reports are historical, not a current route inventory. No active API,
nullable legacy field or persisted reader is removed by this documentation cleanup.

Stage2 runtime uses the frozen [0.10 contract](external/pharmascan-api-openapi-0.10.0.json).
The [0.8](external/pharmascan-api-openapi-0.8.0.json) and
[0.4](external/pharmascan-api-openapi-0.4.0.json) snapshots remain regression resources.
See [upgrade mapping](STAGE2_V010_UPGRADE.md) and [safety principles](SAFETY_AND_EVALUATION.md).
Dated verification statements describe their recorded environment, not current production.

## Agent response provenance and medication-education diagnostics

`AgentMessageResponse.mode` remains a string. `records_only` identifies a deliberate
application-tool/source response without model-generated interpretation; it does
not assert that Gemini is unavailable. Existing `gemini`, `deterministic_degraded`
and quota modes retain their behavior. Update the frontend to display the new
value accurately; old clients remain wire-compatible but may mislabel its origin.

Medication education reuses the `get_long_term_care` database audit category.
The existing public trace `payload.action = get_medication_understanding`
identifies the actual action; the UI displays that action for this specific pair.
No audit enum, database constraint or persisted trace is renamed. Failed education
fallbacks return a blocked trace with a safe error code, not raw exception details;
authentication failures still propagate. A grouped read's `success` alone is not
proof that a label matched: inspect its action and `general_knowledge.status`.

No schema, RLS or production-data migration is required. Local tests do not prove
the deployed runtime or an external knowledge/model provider succeeded.

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

## D. Quality output codes (distinct from visual decision)

- `image_unusable` with flags (only measured) `blur`, `glare`, `too_dark`, `pill_too_small`, `crop_cutoff`, `duplicate_boxes`, `overlap`.
- `quality_unknown` if no validated image quality analyzer exists.
- `good_quality_but_unmatched` requires **both** a validated quality check and calibrated gallery decision.
- `ambiguous_candidates` when score margins insufficient.
- `outside_catalogue_coverage` when known US-only catalogue cannot resolve locally marketed drug.
- `upstream_unavailable` for service error; never map to `unmatched`.

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
See the [worker dispatch and trust boundary](ARCHITECTURE.md#worker-dispatch-transport-boundary).

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

## Assistant patient review bindings

The existing plan-end POST and unfinished-registration DELETE endpoints accept
optional paired `X-Assistant-Task` (UUID) and `X-Assistant-Revision` headers.
Assistant patient reviews bind the authenticated owner, saved task, capability,
current task revision and owned record/version. Partial bindings, stale reviews
and revoked saving permission are refused. Preparation does not execute either
operation; the original independent patient confirmation remains required.
Explicit patient actions outside Assistant retain their existing API.

`GET /api/medications/unfinished/{kind}/{target}/receipt` reads an actual owned
deletion receipt with `Cache-Control: no-store`: `deleted`, `medication_deleted`
and `cleanup_pending`. It exposes no storage paths. An absent receipt is404;
an unsupported receipt reader is503. A missing clinical record does not prove
deletion. Pending cleanup is retried through the original idempotent DELETE.
`kind=source` identifies an evidence enrollment task, not a source document;
workflow references distinguish these as `enrollment_task` and `source`.

The Assistant maintenance integration is currently composed only in the isolated
in-memory profile. Deletion preparation captures the clinical revision and
displays the affected unfinished plan/source-registration counts; changed
records require a new review. Remote revision-guard support is unavailable and
is refused before a persistence call. These contracts do not establish live
database, Storage or deployed acceptance.

`POST /api/agent/workflows/tasks/{task_id}/resume-draft` accepts only
`expected_revision`. It derives the owned original saved task from the selected
regimen's existing enrollment binding, pauses the recovery task and resumes the
original. A client cannot supply a destination task, adopt a revoked task or bypass
its saving control. The response is the current original `WorkflowView`.
Unbound clinical drafts bind once at explicit preparation, without recreating
their medication, source or regimen. Corrections prepare another unactivated
version; the original evidence and values remain intact.

Prepared draft reads may contain `identity_review: {source_id, medication_name}`
when a new instruction version still needs the medication's original name evidence
checked. After the patient's separate name acknowledgement,
`POST /api/medications/drafts/{regimen_id}/identity-review` accepts
`{confirmed: true}` with required current Assistant task/revision headers. It
reviews only the original medication-name field and the same owned medication's
identity; other original fields and source-wide review status are preserved.
The endpoint is unavailable without composed Assistant workflows. Activation
still requires the ordinary source-instruction review and independent confirmation.
Workflow activation challenges bind the saved task revision as metadata; old
challenges issued before recovery or a revision change require a new summary.

`POST /api/evidence/tasks/{source_task_id}/saved-original` accepts only
`{attachment_id: UUID, confirmed: true}` with required `X-Assistant-Task` and
`X-Assistant-Revision` headers. It reads the current task's saved, successfully
extracted original, rechecks owner, permission and registration version, and
returns the actual `EnrollmentTask` with `Cache-Control: no-store`. The operation
key is derived by the server from the current task/revision/target/attachment;
retries reconcile that owned receipt without repeating extraction or creating
duplicate clinical records. Extraction output, owner IDs and storage paths are
not accepted as request overrides. This endpoint is composed only in the local
memory Assistant profile. The two source capabilities are composed in that profile;
remote patient roots remain unavailable until separate persistence acceptance.

`POST /api/evidence/tasks/{source_task_id}/review` accepts the same optional
paired Assistant headers. When supplied, the current owned task and source
version are required. Source review, unactivated-plan creation and the actual
workflow binding publish together in the memory transaction; failed binding
rolls back review flags and clinical rows. It does not activate the plan or
issue a challenge. A source registration already controlled by a saved workflow
requires that original task, including through the ordinary source APIs.
Later duplicate-original references preserve their originals without transferring
registration authority. Legacy unbound source registrations retain their original
independent patient API. Remote transaction equivalence is unavailable.
The raw image source-upload endpoint rejects Assistant headers instead of silently
ignoring them; Assistant saves use the saved-original endpoint above.

Workflow `report_business_result` still accepts no result fields. Explicitly
configured server readers can reconcile a source registration into its actual
workflow-bound regimen reference. Missing records and unbound external changes
do not prove patient success. The ordinary independent activation challenge is
required after the regimen reference is captured.

The embedded source UI reuses the ordinary source-review fields through a typed
patient port, without the ordinary page's browser-storage registration marker or
automatic challenge request. Source save and source review each require their own
patient action. `report_business_result` and explicit task-status checks reconcile
actual receipts after a lost response without submitting another clinical write.
Source and regimen pickers return to the original saved source task; a suspended
task is resumable, while revoked saving, interrupted requests and terminal tasks
remain denied. Stale background recovery/source tasks remain readable and offer
no confirmation instead of failing the entire task list.

Source workflow no-save image previews return page-only extraction evidence and
no enrollment collection fields. Enabling saving explicitly retains the page's
original file through the normal saved-original path before recognition. After a
formally bound plan already exists, enabling saving again reuses its owned actual
binding and unactivated version; it does not recreate source or regimen rows.

### Assistant recorded-plan changes (local memory composition)

`medication.plan.change` uses the existing workflow task/event transport. Its closed
inputs pair an owned `regimen_id`, `expected_version` and observed `expected_state`
(`active`, `ended`, `superseded`) with optional clinical `details`. Details accept
only dose, schedule, route, food instructions and course dates. Product identity,
predecessor linkage, confirmation and first-dose anchor authority are server-owned.
Omitted details retain recorded values; explicit null clears an optional value.
Successive partial detail replies retain earlier changes for the same selected plan.

Selecting a plan or previewing changed inputs never creates a clinical version.
Explicit preparation requires a substantive change and creates an unactivated
version on the same medication. An active predecessor is replaced only through
the existing independent review/challenge/activation APIs; an ended/replaced
target prepares a new course under the existing overlap rules. Old source evidence
and dose reports remain intact. Lost responses reconcile actual action receipts;
draft recovery returns to the original task without transferring its authority.

Current task revision, saving permission and active predecessor are rechecked
before patient review and activation. Local activation failures restore the staged
source/plan/rule/occurrence/challenge state. This capability and transaction are
composed only in the memory Assistant profile; remote SQL/provider/deployment
equivalence is unverified and remains unavailable.

### Assistant record reads and current patient dose reports (local memory)

The memory composition supports typed queries for today/due plans, stored dose
status/history, original source fields, current reviewed instructions, record
catalogue/history, calendar week/month/course summaries and visit questions.
These Assistant reads use pure schedule projections and stored records; they do
not materialize occurrences, create reports, request confirmations or reconstruct
history. History cursors retain the original query scope, patient timezone and
snapshot. Date selections retain DST boundaries; a future history day is refused.
The personal-instructions query does not call the general knowledge provider.

`dose.report` and `dose.prn.report` are patient-UI capabilities. Their workflow
inputs select only an owned `regimen_id` and `expected_version` (plus picker page).
Preparing review stores a minimal plan reference, with no report or challenge.
The embedded patient component then uses the existing due-dose lookup when needed
and the existing separate challenge/report APIs with `X-Assistant-Task` and
`X-Assistant-Revision`. The ordinary due-dose patient lookup retains its existing
bounded current schedule behavior; it is not called by the pure Agent query.

Both headers are required together. The server checks authenticated ownership,
current task/revision, saving permission, selected current plan/version and dose
kind before the patient request. Report operations and actual challenge IDs bind
as minimal metadata; confirmation bodies, tokens and session confirmation state
never enter workflow inputs or model tools. A prior or other-task challenge cannot
be adopted. Header-bound request keys use the patient component's canonical
`report-<lowercase UUID>` form so receipt readback uses the identical key. Existing
patient calls without Assistant headers retain the original API protocol.

Completion comes only from the actual self-report event and its bound confirmed,
consumed challenge. `report_business_result` accepts no client success or event ID.
Unknown responses retain the patient request until actual status is checked;
an unchanged result check advances the task revision and fences the old review,
requiring a new independent summary before a fresh attempt. Confirmed medical
history remains intact. Self-report never proves ingestion. Historical late report
or correction execution is not granted to Agent tools by these capabilities.

`dose.late.review` and `dose.correction.review` select an existing owned scheduled
occurrence from the original seven-day patient policy. Closed workflow inputs are
`occurrence_id`, `expected_version` (append-only report count + 1),
`expected_report_id` and picker `page`. The picker reads existing occurrences
without materializing any dose; its coverage is the newest 50 occurrences.
Preparation binds only a `dose_occurrence` reference. The selected patient form
uses the original late-report challenge/confirmation APIs with the same paired
Assistant headers. The server rechecks task, occurrence, report generation and
saving permission, then requires the original independent patient confirmation.
Status, reason, notes, administration time, request ID and challenge remain outside
workflow/model inputs. Actual completion reads the append-only report plus its
bound confirmed/consumed challenge and returns a `late_report` reference. Original
events and previous corrections are retained. No Agent backfill is introduced.

`medication.knowledge` prepares only a bounded `medication_name` and local name
resolution. It never queries external sources during start/view/list/field edits.
The explicit patient `POST /api/agent/workflows/tasks/{id}/knowledge` request has
`expected_revision`, optional current `candidate_id`, and the existing `ephemeral`
page-input envelope for no-save mode. It returns `MedicationUnderstanding` with
the actual source evidence, coverage and distinct failure explanations. Ownership,
active task, capability, revision and current name choice are checked; fuzzy names
require a current offered candidate. General ingredient names alone are queried,
without private product/record data or personal-dose instructions. Inputs are
checked again after the provider read, refusing stale responses.

Knowledge results remain page state and are not saved as task fields, cached
payloads, fabricated business references or client-asserted completion. Saved
tasks retain the entered name and stay query-ready; reopening requires another
explicit lookup. No-save requests retain no name/body/hash/result server-side.
The response uses `Cache-Control: no-store`. Existing ordinary knowledge chat and
standalone patient reporting APIs retain their protocols.

These workflow additions are composed only in the opt-in memory environment;
dedicated knowledge also requires the knowledge-v2 option. Remote persistence and
actual provider/deployed/device acceptance remain separate gates.

The memory-only care workflow adapter covers `observation.list/add/edit/delete`,
`inventory.view/count`, `barrier.list/add` and
`followup.list/add/edit/contacted/complete/defer/cancel`. `inventory.count` retains
the original six stock-change kinds; no unit or strength conversion is inferred.
Read projections use the public care/observation services and return bounded
pages without materializing doses or reconciling derived supply tasks.

Care drafts accept patient fields only. Server-generated request IDs, patient
identity, `confirmed`, `historical_confirmed` and client success are not workflow
inputs. Explicit preparation saves a `care_review` handle, not a clinical record.
The shared patient review submits through the existing observation, stock, barrier
and follow-up APIs with optional paired `X-Assistant-Task/Revision` headers. These
check owner, current task/revision, saving permission, exact reviewed payload and
current target/version. Only the independent patient UI acknowledges historical
task dates; original no-past-reminder policy still applies.

Saved observation-edit/deletion and stock reviews bind the displayed record or
ledger snapshot. Changed records invalidate old review buttons. Task changes retain
the original service's version and append-only history. In the composed memory
environment native and workflow care mutations share the clinical lock; patient
APIs without workflow headers retain their body/response contracts.

Completion re-reads the actual owned observation, stock transaction, reported
barrier or task-history entry and its patient-action receipt. A delete requires
an actual success receipt; absence alone never proves deletion. Response-loss
replays reuse the same reviewed ID. When a result check finds no saved operation,
the new revision permits draft correction and requires a fresh patient review.
No-save drafts retain no server-side text, snapshot fingerprint or action receipt.
Remote care workflow composition, real persistence and notification acceptance
remain gated separately; this does not enable external notifications or scheduling.

The opt-in memory Assistant also composes five read-only media capabilities:
`gallery.list`, `gallery.photo.view`, `library.list`, `library.pdf.view` and
`library.pdf.download`. Bounded English/Chinese entry phrases start typed queries.
Selections use owned medication/image/file IDs and bounded pages; foreign or
cross-medication references are rejected. Preparation reads public gallery/library
metadata only: it never fetches original bytes, runs image processing or writes a
patient record. Safe projections omit storage paths, checksums, patient IDs,
extraction evidence and URLs. A saved query is not a clinical write or proof that
a file was opened or downloaded.

Original PNG/PDF bytes continue through the existing authenticated no-store
patient APIs, only after a patient click. Blob URLs remain in the mounted page
and are revoked on task/revision changes or unmount; late responses from old
tasks are discarded. Failed loads retain the current selection and require an
explicit retry. PDFs are stored documents, with no newly extracted or reviewed
instructions. Acquisition and processing availability is described below.
Remote/SQL, provider, hosted and device acceptance
remain separate gates.

The same opt-in memory environment composes six native media lifecycle workflows:
`gallery.photo.edit/remove/delete/retire` and `library.pdf.edit/delete`. Closed
drafts bind an owned medication, file/image ID and strict current metadata version.
Preparation creates only an explicit `media_review` handle; it does not save or
delete a file. The patient reviews the target, version, exact edit and consequences
in a separate confirmation sheet before the existing native API is called.

Native photo PATCH/retire and PDF PATCH/DELETE accept optional paired
`X-Assistant-Task` and `X-Assistant-Revision` headers. Bound photo PATCH requires
its original `confirmed` body flag; bound retirement and PDF PATCH also require
the explicit `confirmed=true` query. PDF DELETE retains its native confirmation
query. Unbound patient callers retain their original protocols. Bound requests
recheck current task/save permission, owner, endpoint, target, reviewed payload,
CAS version and source protection. Both bound and unbound lifecycle operations
share the patient clinical lock in this memory composition.

Removing a photo preserves its original bytes; deleting cleans its private file;
retiring only stops comparison eligibility. No image is promoted to a verified
reference. Completion requires a native-success receipt and actual owned metadata
or tombstone. A missing file alone never proves deletion. Partial cleanup remains
pending and requires explicit patient retry; lost responses use result readback,
with no duplicate metadata mutation. Failed saves retain typed draft fields; a
known no-result check is required before correcting an attempted review.

Prepared media receipts retain opaque binding metadata and a fixed status, not
content fingerprints. Native CAS versions and current source protection reject
stale reviews. Already completed actions keep their original receipt/reference
if the file later changes, with an explicit historical-result message. Completed
workflows remain non-executable. No remote media workflow, SQL migration execution,
storage-policy change, provider enablement or clinical instruction extraction is
introduced by these additions.

The opt-in memory Assistant also composes `gallery.photo.add`. Its typed draft
selects an owned medication, image kind, source description and saved original.
Reference originals use `source_kind=reference_photo` and
`extraction_status=not_requested`: storing or recovering them never requests OCR,
even when recognition consent is sent. Medication source preview/enrollment
rejects this kind. The original PNG/JPEG bytes remain distinct from the native
gallery's normalized copy. The existing MIME and 8,000,000-byte limits apply.

Preparing the workflow creates a `media_review`, with no gallery write. The
patient separately confirms the association and private processing. Native
gallery POST accepts optional paired `X-Assistant-Task` and
`X-Assistant-Revision` headers. Bound requests require `reviewed=true`,
`for_comparison=false`, processing consent and the exact saved original bytes,
medication and metadata from the current review. Legacy unbound uploads keep
their existing protocol. This does not verify drug identity, instructions or
comparison eligibility.

A no-save selection remains a page-local File until the patient enables saving
and explicitly saves the original. Saved originals can be recovered after a
refresh or failed upload; an uncertain outcome requires explicit result checking.
Actual native receipts and owned gallery metadata establish completion. Duplicate
bytes never imply that new metadata was applied; removed photos cannot count as
successful additions. Revoking saving cleans the raw draft original while
preserving any independently confirmed gallery copy. Re-enabling saving uses a
new upload ID; response recovery within the same save permission uses the original
immutable ID.

Reference originals are refused before HTTP by the existing Supabase workflow
serializer because its accepted SQL contract supports medication-source kinds
only. No remote composition, migration or storage-policy change is enabled.
Explicit image comparison and source preview are described below. All fifteen
media capabilities are composed only in the opt-in memory Assistant environment.

The opt-in memory Assistant composes `library.pdf.add` through the existing private
PDF library service. Its closed draft binds an owned medication, leaf PDF filename,
native document category, optional description and saved original attachment.
`source_kind=library_pdf` with `application/pdf` is store-only and never enters
image decoding or source recognition. Validated original bytes use the native
10 MiB PDF limit and basic signature/EOF validation; image limits stay 8,000,000
bytes. No PDF content or medical instructions are extracted or verified.

The page-local File and explicit saving transition follow the photo draft flow.
Saved originals support authenticated no-store viewing/download and interrupted
upload recovery; failed library writes retain the exact PDF. Preparing a
`media_review` does not upload to the library. A separate patient sheet confirms
the medication association, filename, category, description and private storage.
Bound native PDF POST requests carry paired `X-Assistant-Task` and
`X-Assistant-Revision` headers plus `confirmed=true`; the server rechecks the
current task and exact reviewed bytes/metadata. Unbound callers keep the existing
upload protocol. The native filename determines the initial display title.

Completion requires a native success receipt and actual owned PDF metadata/version.
Uncertain native responses require result checking and a same-original explicit
retry if no receipt exists; native checksum deduplication prevents a second file.
An existing duplicate keeps its original metadata and a deleted duplicate is
rejected. Revoking draft saving cleans the raw draft PDF while preserving the
independently confirmed library copy. These new original kinds remain refused
before the old Supabase workflow command; remote objects remain image-only and
uncomposed for PDF originals. No migration, provider, cloud or policy enablement
is introduced.

The opt-in memory Assistant composes `image.compare` as an explicit page-only
processing operation. Typed inputs select `personal` (existing personal-reference
rules, optional owned active regimen) or `identify` (catalogue candidate evidence,
no personal regimen). Draft preparation, task reads and resume never process an
image. Store-only `source_kind=comparison_photo` originals retain exact PNG/JPEG
bytes with the existing 8,000,000-byte/decode limits and never run source OCR.
Both saved and no-save comparison tasks reject the medication source-recognition
path. The new original kind is refused before the old Supabase workflow command;
remote comparison workflow composition remains gated separately.

`POST /api/agent/workflows/tasks/{task_id}/compare` streams the current PNG/JPEG
with `expected_revision` and explicit `X-Stage2-Consent: true`. A saved task must
already own its saved comparison original and the submitted bytes/MIME must match
exactly. No-save tasks require `ephemeral_intent` and optional
`ephemeral_regimen_id` to carry current page inputs; saved tasks reject these
overrides. No-save processing saves no original or recognition history. After
processing the server rechecks task/input/save state, original access, owned active
selection and clinical revision; changed or revoked contexts discard the result.
No automatic provider retry is introduced.

Personal checks reuse the native calculation through public `preview_check`,
which saves no recognition history. The original native `check` still saves its
recognition run; that endpoint's protocol/history behavior is preserved. Catalogue
checks reuse `VisualCheckService`. Existing configured demo catalogue processing
and Assistant share the same explicitly composed visual service. Missing providers
return `unavailable`, never a fabricated successful match or missing-reference claim.

Responses distinguish actual `missing_reference`, `unknown`, `ambiguous`,
`conflict`, `match` visual evidence and `unavailable` outcomes with bounded safe
reason keys and catalogue names/strengths only. They omit raw similarity scores,
provider IDs, private paths and write authority. Identity, dosage, safe use, pill
counts and ingestion are never established; `safe_to_take`, `count_reliable` and
`ingestion_proven` remain false. There is no dose event, plan update, reference
promotion or saved workflow result. Results live only in the page; reopening or
retrying requires another explicit consented request. Saved raw originals survive
processing failures until saving is revoked. Provider, SQL, hosted and physical
device acceptance are separate from local synthetic replay evidence.

The opt-in memory Assistant also composes `source.preview`. Its typed draft
selects `package`, `pharmacy_label` or `prescription`; source-kind choices are
interpretation requests and do not verify document authenticity. Raw originals
use the separate store-only purpose `source_preview_photo`. Saving or recovering
an original never runs extraction, even when a recognition header is sent.
This purpose cannot enter the existing saved/ephemeral medication-source
extraction path, become a reviewed source or reach the old Supabase workflow
command. PNG/JPEG validation and the 8,000,000-byte limit are unchanged.

`POST /api/agent/workflows/tasks/{task_id}/source-preview` accepts the current raw
image, `expected_revision` and explicit `X-Stage2-Consent: true`. Saved tasks must
own a retained preview original and the request bytes/MIME must match it exactly.
No-save tasks supply the current page `ephemeral_source_kind`; saved tasks reject
that override. The server calls the existing `SourcePreviewService` only for
this explicit request, then rechecks the task/save/input/original and clinical
revision. Changed or revoked contexts discard late results. The narrowly
allowlisted processing queries are `image.compare` and `source.preview`;
`reminder.calendar.export` separately permits the bound calendar read described
below. Other device/write capabilities acquire no query or execution authority.

Responses distinguish successful extraction (including an empty candidate list),
provider unavailability and rejected source evidence. Returned source kind must
match the typed request and `provider_source` must be `photo`. No automatic retry
occurs. Printed evidence remains untrusted, `review_required=true` and candidate
`can_activate_regimen=false`. The UI reuses printed-evidence rendering with
preview-specific wording; it presents no implied plan form or save confirmation.
Clock words, quantity, dates and expiry do not become saved dosing instructions.

Preview results stay in page memory, never in workflow fields, attachment
extraction metadata, clinical sources, recognition history or dose/plan records.
Failures retain saved raw originals until saving is revoked; no-save retains
the File only in the page. Reopening requires another explicit consented read.
Saving medication/source information remains a separate reviewed workflow and
is never inferred from preview success. Configured demo composition shares its
existing source service and ID generator with the native operation, with no new
provider configuration. Native `/api/sources/preview` protocol is unchanged;
SQL/provider/deployed/device acceptance remains separate.

### Assistant reminder reads and calendar export

The opt-in memory composition exposes `reminder.list`,
`reminder.calendar.export` and `notification.status`. Reminder changes are
described separately below; notification device actions have separate patient
controls and sending gates. These three read operations do
not complete a patient write or create a workflow business-result reference.
Saving a query preserves its task, not a device permission or delivery receipt.

`reminder.list` accepts closed fields `days` (1–7, default 7) and `page`
(zero-based). It uses the existing calendar projection in the patient's IANA
timezone; it does not call the materializing upcoming-reminder API or create
dose occurrences. The projection includes ten medication rows per page, up to
ten actionable care-task reminders and ten existing saved snoozes. Projected
occurrence identifiers do not confer snooze or dose-report authority. Only
owned, bounded metadata is returned, without original evidence or storage paths.

Calendar fields are `range` (`30`, `90`, `remaining`, `custom`), optional paired
custom ISO dates, and strict `include_medications` / `include_tasks` booleans.
At least one content category is required. The existing native form and
`GET /api/reminders/calendar` retain their date, coverage and ICS validation.
An Assistant request supplies paired `X-Assistant-Task` and
`X-Assistant-Revision` headers; incomplete bindings are rejected. Saved
tasks must match their current typed options. No-save requests use the current
page's options without persisting them. The bound route rejects the legacy
`days` alias and rechecks task/options and clinical revision after rendering.
Unbound native callers retain their existing protocol.

Opening or cancelling the form does not export. The patient explicitly exports
an `.ics` file; it is not automatically imported into a device calendar or kept
as a workflow attachment. Failed exports retain form choices. Late responses
after task change or component unmount cannot initiate a download.

`notification.status` has no input fields. Its explicit page button reads the
existing application push configuration and current browser subscription status.
Only availability, support, subscription state and browser permission are shown;
subscription identifiers, endpoints and keys are excluded from workflow/model
requests and history. This query never requests permission, registers or removes
a subscription, or sends a test notification. A subscription is not evidence
of delivery. Local synthetic browser checks do not establish physical-device,
SQL, provider or deployed acceptance.

### Assistant snooze and reminder settings

The opt-in memory composition also exposes `reminder.snooze` and
`reminder.settings`. Collection and preparation never save a reminder, update
preferences, materialize dose occurrences, change a regimen or record ingestion.
Only an existing owned, open occurrence of a current reviewed plan can be
snoozed. Offered choices identify the medicine and scheduled local date/time;
projected identifiers alone cannot become saved occurrences.

Snooze fields are `occurrence_id`, strict `minutes` (1–1440), nullable
`previous_remind_at` and `previous_timezone`. Reminder settings are limited to
strict `reminders_enabled` and `reminder_lead_minutes` (0–120), plus
`previous_enabled`, `previous_lead_minutes` and `previous_timezone` for current
state comparison. Missing fields remain a draft. Native timezone, language,
voice, history and other profile changes are outside this capability. Current
reminder/preference state and the prepared clinical revision are checked again
before the patient write, under the shared patient clinical lock.

A saved complete draft prepares a `reminder_review`; the patient opens a
separate review sheet and explicitly confirms. The existing
`POST /api/reminders` or `PUT /api/me/preferences` accepts the paired
`X-Assistant-Task` / `X-Assistant-Revision` headers and
`X-Patient-Confirmed: true`. The bound body must exactly match the reviewed
native fields. Incomplete bindings, changed fields, wrong owner, stale or
paused tasks, revoked saving and no-save drafts cannot fall back to an unbound
write. Unbound native protocols and the original snooze deadline policy remain
available. No notification permission, subscription or sender is activated.

Native-success replay reads the current owned record without another save.
Because the native snooze calculates its time from the request, a response loss
must be followed by result checking rather than another snooze. A real native
success receipt produces a `reminder_action` reference to that operation
receipt; it does not invent a native row ID or claim the latest state is the
original result. Completed tasks describe the earlier saved change and label
readback as current settings/snooze. If no success receipt exists, a changed
native state remains uncertain and cannot authorize replay or replacement of
the draft. An unchanged before-state permits checked editing and a new
independent review. Failures retain input; no automatic retries occur. These
workflow receipts add no dose event or clinical audit/history mutation.

### Assistant device notification actions

`notification.subscribe`, `notification.unsubscribe` and `notification.test`
open scoped patient controls in the opt-in memory composition. Their closed
workflow DTO has no fields. Subscription endpoints, keys, native subscription
identifiers and test request IDs are never accepted as workflow/model inputs
or saved in conversation history. Device adapters have no model writer or
business-result reference. Preparing or reopening a task does not request
permission, register a service worker, subscribe, revoke or send.

The patient opens the sheet, checks the current native status and confirms
the action separately. Subscribe reuses the existing browser Web Push flow;
permission is requested only after that click and only if configuration and
browser support permit it. Bound subscribe refuses implicit key rotation:
the patient must separately turn off the old subscription. Unsubscribe supports
the current browser, one owned saved device or all owned devices; the latter
requires an explicit scope choice and confirmation. Native identifiers remain
page-local, and the original backend enforces ownership on each revocation.
Permission itself is browser-managed and is not reversed by deleting a task.

Native subscribe, revoke-current, revoke-ID and test endpoints accept optional
paired `X-Assistant-Task` / `X-Assistant-Revision` headers plus
`X-Patient-Confirmed: true`. Bindings require the matching active, current,
saved task. No-save, revoked, paused, stale, wrong-owner and cross-operation
requests cannot fall back to an unbound write. The original unbound native
protocols remain compatible. Browser steps recheck current page/task context
after awaited operations and before subsequent private saves. No read-only
query allowlist or clinical write authority is expanded.

`GET /api/reminders/push/config` also accepts the paired binding for these
device tasks. Bound `test_available` requires the existing sender, verified
authentication and the separate composition-only notification-send approval,
which defaults to false. This approval cannot be set by model or request input.
The capability catalogue keeps `notification.test` unavailable with
`notification_send_not_authorized` until approved; a deterministic explanation
entry can still open its disabled patient controls. Device capabilities are
excluded from the model's executable tool catalogue.

A bound test requires independent confirmation and all server gates again.
A content-free per-task attempt receipt prevents a second send from the same
task, including unknown failures and requests after the native 60-second cache
expires. No automatic retry occurs. A provider acceptance is displayed as
acceptance only; it does not prove device receipt. The patient's receipt answer
stays in the page and is not a system delivery receipt.

Failed subscription persistence can leave a browser subscription; failed
all-device cleanup can leave a partly revoked account. The sheet reports that
uncertainty and requires an explicit status check before another change.
It does not invent rollback or delivery. Local acceptance uses a synthetic
repository, browser permission/PushManager and recording sender; it never
establishes SQL, real-provider, deployed or physical-device delivery.

### Assistant preferences, care contacts and secure account

The opt-in memory composition supports `profile.view`, `profile.edit`,
`preference.language`, `preference.text`, `preference.voice`,
`preference.reminder`, `preference.privacy` and `preference.timezone`.
Each write has its own closed native field set and typed prior public-profile
snapshot. Preparation creates a `settings_review`, never a profile/clinical
write. The original preference API requires a current paired task/revision,
explicit patient confirmation and the exact reviewed fields. The existing
`reminder.settings` binding remains separate and compatible. Voice preferences
grant no microphone/cloud permission; chat-saving changes do not delete chats
or clinical records. Timezone changes refresh the native display without
rewriting historical reports.

`caregiver.list`, `caregiver.add`, `caregiver.edit` and `caregiver.delete` use
the original owned caregiver service. Supplying new contact details to a
workflow requires explicit `storage_consent=true` before task persistence;
until then the native shared fields keep input only on the page. Edit/delete
reviews bind the prior owned details and update instant, not only a contact
identifier. Original native caregiver APIs accept the optional paired binding
and `X-Patient-Confirmed: true`; incomplete, changed, wrong-owner, paused,
no-save or revoked requests cannot fall back to an unbound mutation. Unbound
protocols retain the original behavior. Contacts remain pending verification,
with notifications and record sharing disabled; no invitation is sent.

A native success plus actual owned readback produces a `settings_action`
reference to the immutable operation receipt. It proves the earlier change;
the UI separately labels current values. A lost response cannot overwrite
later native changes or duplicate creation/deletion. Failures retain input;
only a checked unchanged state permits editing and a new independent review.
An applied write without a success receipt remains uncertain. Preparation,
preference changes and contact CRUD grant no dose/regimen/history authority.

`account.status`, `account.login`, `account.link`, `account.password` and
`account.signout` have empty workflow input and emit only `SecureAccountAction`.
They open the existing native account form after an explicit click, with no
model writer or workflow business-result reference. Email, passwords, codes
and tokens stay in the native `AccountPort`/Auth SDK boundary; they are never
workflow fields or events. Existing account-switch consent, push cleanup before
signout and identity reset/reload remain authoritative; guest records are not
merged into another owner. Closing/unmounting discards the form's secrets.
Local Auth unavailability is shown honestly. Recording-port tests and synthetic
memory/browser checks do not establish real Auth/email, SQL, provider or
deployed acceptance.

### Assistant conversation and support actions

`conversation.list` and `conversation.view` project bounded, owned conversation
titles and text through the existing thread service. Historical text never
restores executable tools or confirmations. `assistant.usage` reads actual
current usage without exposing owner identity; an unavailable service is
distinct from zero remaining quota.

`conversation.new`, `conversation.resume` and `conversation.clear` prepare
patient page actions. The existing `/api/demo/start`, conversation resume and
history DELETE endpoints accept optional paired `X-Assistant-Task` /
`X-Assistant-Revision` headers plus independent `X-Patient-Confirmed: true`.
Bound new-session requests require `session_id: null`. Current owner, saved
permission, task revision, capability and selected conversation must match.
Actual session readback and operation receipts prevent duplicate session
creation after response loss. An uncertain attempted result is not repeated;
changing an attempted task requires a new task. A successful clear receipt
replays its result without deleting conversations created later. Clearing
detaches the active page binding and resets native history views while retaining
saved workflow drafts and clinical records. Original unbound endpoints retain
their protocols.

`feedback.submit` collects native category/message fields, prepares an independent
review and submits through the existing `/api/feedback` endpoint with the same
optional current-task headers. The feedback ID comes from the prepared review.
An owned persisted record plus success receipt is required before reporting
completion. Failed input remains available; an unchanged-result check permits
editing and a new independent review. Feedback saved without a success receipt
remains uncertain and cannot be blindly resubmitted. Feedback is stored locally
to the account record; saving makes no email, delivery or human-review claim.

`speech.input` and `speech.playback` prepare explicit device controls and retain
the original voice/provider preferences. Transcripts enter the editable composer
and require Send; playback text stays on the page. Preparation grants no device
permission or cloud processing. `help.open`, `guide.start` and `navigation.open`
open existing app content only after a patient click. Navigation accepts native
routes and closed, owned UUID target fields, never arbitrary URLs or query data;
the client revalidates the projection and retains the Assistant origin for Back.
These adapters are enabled in the synthetic memory composition only. Recording
speech tests do not establish real device/provider or deployed acceptance.

### Capability coverage and stale task projections

Discovery distinguishes an implemented capability disabled by configuration
(`feature_disabled`) from a missing adapter (`not_implemented`). General
medication knowledge defaults to its existing feature gate; enabling workflows
does not implicitly enable knowledge providers or notification sending.
The additive `implemented` flag reports a registered application adapter,
independently of `available`. Missing services or notification authority can keep
an implemented capability unavailable. `persistence_not_ready` reports that
request-scoped transaction components exist but the persistent workflow graph is
not enabled; it does not assert database or role acceptance. These discovery
flags do not change authorization on unbound native patient endpoints.
`CoverageResult` records one capability/case/environment with `PASS`, `PARTIAL`,
`NOT_RUN`, `UNAVAILABLE` or `FAIL`. Passing evidence requires an evidence path;
non-passing outcomes require a reason. The executable phase index lives in
`tests/fixtures/assistant/capability_coverage.json`; dated execution evidence
remains private. Recording ports and synthetic provider replay do not establish
real Auth, database, provider, device or deployed behavior.

A verified native observation write retains its operation receipt when that
observation is later edited or removed. Task projections label historical
success separately from current record availability; they do not reconstruct
or restore an old observation. Stale selected file/follow-up versions remain
readable with original draft input and explicit current-version reselection.
They cannot silently adopt a newer version or block unrelated saved drafts;
cross-medication file selection still fails ownership checks.

Independent follow-up reviews show the proposed title/category and a readable
owned medication/plan association, or explicit association removal. Saving
continues through the unchanged native patient-confirmation API and exact
reviewed payload. These additions do not rewrite clinical or audit history.

### Assistant runtime progress (opt-in memory profile)

`ASSISTANT_PROGRESS_ENABLED` defaults to false and requires composed Assistant
workflows. The capability manifest adds `progress_enabled`; an absent field
means unsupported for older clients. No persistent-environment memory fallback
is introduced. With progress off, the existing JSON message behavior is retained.

`POST /api/agent/workflows/messages/stream` accepts the existing workflow message
plus a caller-generated UUID `run_id`. It uses the same validated application
handler as `POST /messages`. Fetch uses the existing bearer header; credentials
are never placed in a stream URL. SSE `progress` frames carry ordered, content-free
`RunEvent` records, followed by one `result` frame containing the complete validated
`WorkflowMessageResponse` only on success. Medical text is not emitted token by
token. Duplicate run IDs are refused (409), rather than re-executed.

`GET /api/agent/workflows/runs/{run_id}` returns owner-scoped status, metadata and
events; `POST /runs/{run_id}/cancel` requests cooperative cancellation. Foreign
or unknown runs are 404; disabled progress is 503. Normal JSON responses add an
`X-Agent-Run-ID` header when this runtime is enabled. Stop does not undo an entered
or committed clinical transaction. It prevents subsequent steps and late chat
or context writes; synchronous I/O may finish within its timeout before stopping.
Disconnect requests cancellation, waits for the worker and closes request-scoped
resources once. The client never repeats a message POST on disconnect; it may read
run status. Its waiting limit is 60 seconds.

That waiting limit includes initial authentication/headers and any disconnect
reconciliation GET. Status reads also bound body consumption (45 s, capped by
the caller's remaining lifetime,64 KiB), cancel their reader and validate the
returned run ID. A recovered running request remains stoppable through its
owner-bound run state after the original stream controller has been disposed.

Each enabled run has a 45-second monotonic deadline, at most four logical model
calls and four logical tool calls. Native Gemini (12 s) and knowledge (6 s)
timeouts are capped by the remaining time; SDK retries recheck the same deadline
and are counted separately, without replaying tools. Run metadata holds actual
instruction/schema hashes, source revision when available, actual application
code hash, measured durations and observed SDK usage. Unavailable model/SDK/token
values remain null; `usage_responses` identifies the coverage of any partial usage
aggregate. No prompt, patient text, image, tool arguments/results, bearer token or
hidden reasoning is stored in these records. Historical session version fields
are retained for compatibility and are not presented as the current model's
instruction version. Cancellation storage is process-local, shared by injected
service instances; SQL, multiple workers, providers and hosted streaming require
their own acceptance evidence.

Valid actual SDK usage/model metadata is retained even when executable reply
content is rejected as malformed; recording usage does not authorize its tools
or make that reply successful.


## Task-independent native media verification

Native gallery/PDF/source/draft APIs preserve their existing request/response DTOs, ownership, consent and confirmation requirements. Internal `NativeMediaUploadIntent` and `NativeMediaDeleteIntent` bind a stable operation ID to an owned bucket/key and immutable target. Claimed external effects are not automatically repeated after timeout or an unknown outcome.

`NativeMediaTicket` identifies a nonce/generation. `NativeMediaObservation` records verified bytes, observed absence after deletion, or an unknown result; `VerifiedNativeMediaRef` carries only the correlated technical proof. A same-patient fixed RPC reserves/claims/settles intents. A separate restricted connection records the fifth fixed native-media observation; patient callers cannot self-assert it.

Existing native publication adopts a matching byte proof in its own metadata transaction. Deletion publishes cleanup acknowledgement only after current tombstone/reference checks, key exclusion and independent actual absence. Safe historical files remain readable; untracked legacy writers and noncanonical cleanup keys can remain `cleanup_pending` until verified reconciliation. Metadata deletion does not prove physical deletion. No new public clinical or verifier HTTP endpoint is introduced.
