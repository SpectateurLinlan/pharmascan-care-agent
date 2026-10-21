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
