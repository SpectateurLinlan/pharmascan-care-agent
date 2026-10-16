# PostgreSQL Data Model — source, medication, regimen, visual evidence, adherence and Agent state

## Implemented long-term additions (migrations022–023)

`patient_medications` has many append-only `inventory_transactions`, scoped by owner+concrete identity+count unit; label quantity remains in source extraction evidence. `regimen_versions` may be referenced by patient-reported `adherence_barriers` and `medication_care_tasks`, never overwritten. Barriers optionally reference an owned task. Tasks retain original source and a bounded transition history/version; completion/deferral/cancellation preserves prior entries.

Existing `health_observations` now optionally stores validated numeric measurements. All old descriptive notes remain valid. Existing `notification_deliveries` has either its original occurrence/regimen/rule or an owned task, enforced by an exclusive-source check and owner foreign keys; unique task/device/time prevents repeated delivery jobs.

022 adds schema/atomic RPCs/FORCE RLS,023 tightens changed human-task retry payload rejection. Both applied to development, no rollback or data deletion. Patient-owned RPC ownership is `auth.uid()`; no arbitrary owner input or direct authenticated stock/task DML. The administrative worker retains its explicit separate connection. Exact fields, rules and rollback scope: [LONG_TERM_CARE](LONG_TERM_CARE.md).

**System of record:** Supabase PostgreSQL, Supabase Auth and private object storage. The current personal embeddings are bounded typed JSON; the earlier `pgvector` target below is not the implemented gallery storage. **Do not put relational/PHI records into Hugging Face model Space**. These are target schemas, **not migrations already run**. See [architecture](ARCHITECTURE.md) and [safety](SAFETY_AND_EVALUATION.md) for patient isolation, traceability and testing boundaries.

## A. ER design and key ownership

```mermaid
erDiagram
  PATIENT_PROFILE ||--o{ PATIENT_MEDICATION : owns
  PATIENT_PROFILE ||--o{ SOURCE_DOCUMENT : uploads
  MEDICATION_PRODUCT ||--o{ PATIENT_MEDICATION : catalogued_as
  PATIENT_MEDICATION ||--o{ REGIMEN_VERSION : has
  REGIMEN_VERSION ||--o{ DOSE_RULE : schedules
  REGIMEN_VERSION ||--o{ DOSE_OCCURRENCE : produces
  DOSE_OCCURRENCE ||--o{ DOSE_EVENT : reports
  PATIENT_MEDICATION ||--o{ VISUAL_REFERENCE_SET : represents
  VISUAL_REFERENCE_SET ||--o{ MEDICATION_IMAGE : stores
  MEDICATION_IMAGE ||--o{ IMAGE_EMBEDDING : encodes
  PATIENT_PROFILE ||--o{ HEALTH_OBSERVATION : logs
  PATIENT_PROFILE ||--o{ CARE_TASK : plans
  PATIENT_PROFILE ||--o{ AGENT_SESSION : owns
  AGENT_SESSION ||--o{ AGENT_TOOL_CALL : records
  PATIENT_PROFILE ||--o{ CAREGIVER_CONTACT : consents
  SOURCE_DOCUMENT ||--o{ SOURCE_FIELD : contains
  REGIMEN_VERSION }o--|| SOURCE_DOCUMENT : cites
```

Do **not** combine `MedicationProduct`, `PatientMedication`, `RegimenVersion`, `VisualReferenceSet` and `DoseEvent` into a single wide table. A product is a concrete market/strength/form identity; patient medication is a user's longitudinal association; regimen is a *time-bounded instruction version*; visual reference is evidence of appearance; dose event is **patient self-report** independent from recognition.

## B. Core tables and fields (types are PostgreSQL suggestions)

| Table | Primary key and columns | Relationships, indexes and constraints |
|---|---|---|
| `patient_profiles` | `user_id uuid PK` (references `auth.users.id`), `display_name text?`, `timezone text NOT NULL DEFAULT 'Asia/Singapore'`, `language text DEFAULT 'en'`, `visual_check_mode enum(SMART,ALWAYS_SUGGEST,REMINDERS_ONLY)`, `voice_default bool`, `is_demo bool`, `created_at timestamptz` | Unique user; one row/account; no NRIC; auth.uid isolation |
| `caregiver_contacts` | Migration020: composite PK(patient_id,id), owner profile FK, name/relationship, contact_type(email/phone), normalized contact_value, storage_consent=true, verification_status=pending only, notifications_enabled=false,sharing_enabled=false,created_at,updated_at,demo_only | unique(patient_id,contact_type,contact_value); owner FORCE RLS; contact storage only. Independent verification, account linking and delivery are future capabilities. |
| `source_documents` | `id uuid PK`, `patient_id uuid FK`, `source_kind enum(pharmacy_label,prescription,package,user_manual,mock_import)`, `storage_path text?`, `issued_at timestamptz?`, `uploaded_at timestamptz`, `is_synthetic bool`, `checksum text?` | private bucket; retention; idempotent duplicate uploads per patient/checksum as appropriate |
| `source_fields` | `id uuid PK`, `source_id uuid FK`, `field_name text`, `field_value jsonb`, `evidence_span text?`, `extraction_method text`, `confidence_raw numeric?`, `review_status enum(extracted,user_reviewed,professional_verified,rejected)` | index(source_id,field_name); extracted OCR not confirmed instructions |
| `medication_products` | `id uuid PK`, `generic_name text`, `brand_name text?`, `strength_value numeric?`, `strength_unit text?`, `dosage_form text`, `release_type text?`, `manufacturer text?`, `market_code text`, `local_registration_code text?`, `external_catalogue_id text?`, `created_at` | index(norm_name,strength,form,market), unique null-safe market/registration when available; do **not** globally unique generic drug name |
| `product_ingredients` | `id uuid PK`, `product_id uuid FK`, `ingredient_name text`, `normalised_identifier text?`, `amount numeric?`, `unit text?`, `mapping_source text?` | many-to-one; indexes(product_id), (normalised_identifier); DDI coverage status separately |
| `patient_medications` | `id uuid PK`, `patient_id uuid FK`, `product_id uuid? FK`, `display_name text NOT NULL`, `source_id uuid? FK`, `identity_status enum(unverified,user_reviewed_document,professional_verified)`, `created_at timestamptz`, `archived_at timestamptz?` | index(patient_id,created_at); cannot conclude specific product from image alone |
| `regimen_versions` | `id uuid PK`, `patient_medication_id uuid FK`, `source_id uuid? FK`, `version_no int`, `state enum(draft,active,ended,superseded,pending_clarification)`, `dose_amount numeric?`, `dose_unit text?`, `frequency_rule jsonb?`, `route text?`, `is_prn bool`, `food_instruction text?`, `source_reviewed_at timestamptz?`, `effective_from timestamptz?`, `effective_to timestamptz?`, `supersedes_id uuid? FK`, `created_at` | unique(patient_medication_id,version_no); partial unique ACTIVE regimen per medication **if clinically appropriate**; end >= start; active requires reviewed source & required schedule fields; retain all superseded versions |
| `dose_rules` | `id uuid PK`, `regimen_id uuid FK`, `local_time time?`, `days_of_week smallint[]?`, `rule_kind enum(scheduled,prn)`, `timezone text`, `enabled bool` | compare schedule in patient timezone; no occurrence inferred for PRN unless documented |
| `dose_occurrences` | `id uuid PK`, `patient_id uuid FK`, `regimen_id uuid FK`, `due_at timestamptz`, `status enum(scheduled,past_due,closed)`, `rule_id uuid?`, `generation_key text` | unique(patient_id,generation_key); indexes(patient_id,due_at); time window ≠ intake outcome |
| `dose_events` | `id uuid PK`, `patient_id uuid FK`, `occurrence_id uuid? FK`, `regimen_id uuid? FK`, `event_time timestamptz`, `intake_status enum(reported_taken,reported_not_taken,unsure,not_reported)`, `visual_status enum(not_checked,visually_consistent,ambiguous,unmatched,image_unusable)`, `recognition_run_id uuid? FK`, `evidence_method enum(self_report,photo_assisted,caregiver_report)`, `idempotency_key text`, `created_at` | unique(patient_id,idempotency_key); index(patient_id,event_time); do not equate confirmation with ingestion; status transitions validated in service |
| `visual_reference_sets` | `id uuid PK`, `patient_medication_id uuid FK`, `product_id uuid?`, `reference_type enum(personal_loose_pill,patient_package,catalogue_seeded_candidate,printed_blister,unprinted_blister)`, `verification_status enum(unverified,user_source_linked,professional_verified)`, `model_space text?`, `created_at`, `ended_at?` | references for history never automatically deleted; only `personal_loose_pill` eligible for existing `/match` unless a model is explicitly validated for other inputs |
| `medication_images` | `id uuid PK`, `reference_set_id uuid? FK`, `patient_id uuid FK`, `image_type enum(loose_front,loose_back,box,pharmacy_label,printed_blister,unprinted_blister,dose_check)`, `storage_path text`, `source_id uuid?`, `sha256 text`, `retain_until timestamptz?`, `consent_scope text?`, `created_at` | private object storage; index(patient_id,reference_set_id); daily dose check images short-lived by default, only recognition metadata persisted |
| `image_embeddings` | `id uuid PK`, `image_id uuid FK`, `embedding vector(256)`, `embedding_space_id text NOT NULL`, `encoder_name text`, `encoder_version text`, `preprocess_version text`, `normalised bool?`, `generated_at` | check all vector values finite in application; no compare across spaces; index(embedding_space_id,image_id); avoid ANN for tiny patient gallery |
| `recognition_runs` | `id uuid PK`, `patient_id uuid FK`, `image_id uuid?`, `task_kind enum(dose_check,unknown_pill,enrollment_reference)`, `image_quality_status text`, `decision text`, `catalogue_candidates jsonb?`, `model_version text?`, `embedding_space_id text?`, `threshold_version text?`, `tool_trace_id uuid?`, `completed_at timestamptz`, `status enum(success,partial,failed)`, `failure_reason text?` | index(patient_id,completed_at); no 'verified identity' derived from similarity; raw response scrubbing |
| `patient_conditions` (P2 optional) | `id uuid PK`, `patient_id uuid FK`, `condition_name text`, `code text?`, `source_id uuid?`, `reported_at timestamptz`, `verification_status text` | optional; diagnosis never inferred from prescribed drug or Gallery similarity |
| `health_observations` | `id uuid PK`, `patient_id uuid FK`, `observation_kind text`, `numeric_value numeric?`, `unit text?`, `text_value text?`, `observed_at timestamptz`, `source enum(patient_report,device_demo,documented)`, `created_at` | index(patient_id,observation_kind,observed_at); units consistent, no diagnosis inferred |
| `care_tasks` | `id uuid PK`, `patient_id uuid FK`, `kind enum(screening,vaccination,followup,medication_review,lifestyle,refill)`, `title text`, `source_id uuid?`, `due_at timestamptz?`, `state enum(pending,done,cancelled)`, `origin enum(user_provided,reviewed_source,demo_seed)`, `created_at` | no AI-created clinical screening indication without source/user request |
| `agent_sessions` | `id uuid PK`, `patient_id uuid FK`, `intent text?`, `state text`, `pending_slots jsonb`, `confirmation_token_hash text?`, `prompt_version text`, `state_version int`, `updated_at timestamptz`, `expires_at timestamptz?` | index(patient_id,updated_at); optimistic concurrency; never store unsanitized complete patient records in prompts |
| `agent_tool_calls` | `id uuid PK`, `session_id uuid FK`, `patient_id uuid FK`, `tool_name text`, `tool_status enum(started,success,failed,blocked,simulated)`, `request_summary jsonb`, `response_summary jsonb`, `policy_rule_id text?`, `provider_request_id text?`, `duration_ms int?`, `called_at timestamptz` | trace audits without secrets/PII; index(session_id,called_at) |
| `notifications` | `id uuid PK`, `patient_id uuid FK`, `caregiver_id uuid? FK`, `kind text`, `delivery_status enum(pending,delivered,failed,simulated,blocked)`, `due_at timestamptz?`, `sent_at timestamptz?`, `consent_snapshot jsonb?` | never falsely indicate `delivered` on mere queue insertion |
| `audit_events` | `id uuid PK`, `patient_id uuid FK`, `actor_type text`, `entity_type text`, `entity_id uuid`, `action text`, `before_redacted jsonb?`, `after_redacted jsonb?`, `occurred_at timestamptz` | tamper-evident intent, clear retention, no secrets or raw images |

## C. Important relational constraints and performance

- **Foreign keys and ownership consistency** across patient-owned joins: a dose event cannot point to another patient's regimen or recognition run. Enforce via service checks or composite foreign keys, not only RLS UI filtering.
- **Patient isolation**: `auth.uid() = patient_id` for every owned table, or join policy through parent ownership. Private storage bucket signed URLs and appropriate storage policy. Backend `service_role` bypasses RLS: never send it to browser, and do not rely solely on RLS if server uses elevated key; validate patient scoping in service.
- **Index** `(patient_id, effective_from/effective_to)` via join/snapshot for active regimens, `(patient_id, due_at)` for dose occurrences, `(patient_id,event_time)` for dose events, `(patient_id,observed_at)` observations, `(session_id,called_at)` tool logs, `(reference_set_id, image_type)` images.
- **Vectors**: `vector(256)` is valid only after exact embedding width verified. If model upgrade changes dimensions, add dimensioned table/version or migrate intentionally; don't coerce unrelated embedding spaces. Small Gallery requires exact cosine, not premature approximate vector search. Even if L2-normalized, semantic confidence must be empirically calibrated.
- **Regimen state**: require source-reviewed quantity/frequency/etc to mark `active`; historical rows stay immutable. A replacement requires an explicit stop of the previous recorded plan before activation; activation no longer automatically supersedes an active plan. Previous events remain attached to their original version.
- **Time**: UTC timestamptz database, patient IANA timezone for planned local doses; `created_at` ≠ occurrence time; never infer ingestion from reminders.
- **Demo seeding**: create synthetic products and 7-day patient records with deterministic seed, idempotent per demo user; use fresh anonymous `auth.uid()` per evaluator, explicit Reset Demo. Protect anonymous creation from spam and schedule cleanup.
- **Images**: original uploaded photo optionally retained for enrollment references; dose-check original short retention or inference-only with results retained. Preserve ability to recompute embeddings if consent/source allows after model change. Never use `.hf.space` as patient gallery database.

## D. Minimal P0 migration order

1. `patient_profiles`, `medication_products`, `patient_medications`, `source_documents`, `source_fields`.
2. `regimen_versions`, `dose_rules`, `dose_occurrences`, `dose_events`, indexes and RLS; synth seed.
3. `visual_reference_sets`, `medication_images`, `image_embeddings`, `recognition_runs` + version checks.
4. `agent_sessions`, `agent_tool_calls`, `audit_events`.
5. P1: `health_observations`, `care_tasks`, `caregiver_contacts`, `notifications`.

**Test migrations in temporary/local PostgreSQL before Supabase production**. Keep down/migration rollback strategy, never destructive changes without backup/approval.

**Optional conditions:** if the later personalisation roadmap needs known diagnoses, add `patient_conditions` with patient-reported or documented provenance; not required for pill Gallery or regimen check, and should never be populated by predicting diagnoses from medication names.

## Implemented additions (2026-10-14)

Migration006 adds bounded nullable immutable source_documents.extraction_evidence JSON, separate from reviewed dose/frequency source_fields. This is patient-submitted untrusted provenance; no cryptographic provider-origin claim. Printed.value/line, source kind, product fields and null regimen fields are retained.

Migration007 dose_reminders: patient_id + occurrence_id primary key/composite FK, remind_at UTC, demo_only=true, owner RLS and future/open-active occurrence guard. Updating snooze preference does not update regimen rules or write dose events. No delivery receipt, closed-browser scheduler, SMS or caregiver consent capability is implied.


## Current additions008-012

008 extends existing patient_profiles with generated speech_locale derived from language, text_size,voice_enabled,tts_autoplay,reminder_lead_minutes,updated_at. Existing language/timezone remain authoritative; existing owner RLS is retained. No duplicate patient_preferences table.

019 adds patient_profiles.text_scale_percent integer NOT NULL DEFAULT100 CHECK100..150. Existing Large values are backfilled125, and an invoker compatibility trigger keeps legacy text_size updates aligned with the numeric value. RLS, ownership and normal same-JWT Data API grants are retained. Applied to the development database after001-018 ledger/hash validation; rollback file exists but was not executed. This changes UX preferences only, not medication data.

009 extends existing agent_sessions with bounded version1 JSON context and generated medication/regimen/occurrence reference columns constrained by same-owner composite FKs. Recent turns<=6; summary<=600 characters; JSON<=20KB. No vector memory or audio storage.

010 demo_ai_usage(patient_id,usage_date,llm_user_turns,model_requests,updated_at,demo_only) and nonce-hash-backed demo_ai_turns reservations are owner-readable/FORCE RLS, without direct authenticated DML. Narrow accounting RPCs serialize per-owner/day reservations; successful+pending reservations cannot exceed20. Pending leases expire after10 minutes. A failed request never refunds an already successful turn. In-flight completion belongs to its original Singapore date. Admin-only private.demo_ai_config defines the server cap.

011 course_start_date/course_end_date are calendar dates separate from effective_from/effective_to. Reviewed source_fields evidence binds activation; active/historical course dates are immutable. Occurrence/event guards reject calendar dates outside the inclusive bounds. Late scheduled reports are evaluated using occurrence date; PRN uses report date. Expired courses retain history and version records.012 forces RLS on existing dose_reminders; schedule/intake authority remains absent.

All new up migrations are applied in development. Rollbacks are not executed against the shared database; disposable database acknowledgement is required.006/007 ledger entries were restored only after actual schema/function/trigger/owner-policy verification.


Migration013 patient_feedback: composite(patient_id,id) primary key, profile owner FK, bounded category/text, demo_only=true, ENABLE/FORCE RLS and owner policy, authenticated SELECT/INSERT only. Feedback content is excluded from Agent context/logging and is not a clinical notification. No reminder timer/schedule table duplication was introduced; new alerts reuse dose occurrences/events and existing snooze records. Food instructions and course dates reuse reviewed regimen/source fields.

## Actual patient-experience persistence revision

Read-only runtime inspection found no health_observations, caregiver_contacts or personal gallery table despite target diagrams above. Migration014 creates health_observations: composite owner/id PK, owned optional medication FK, patient_reported source, bounded descriptions/notes/severity, occurred/created/updated UTC timestamps, demo_only=true, indexed owner/time, ENABLE+FORCE RLS owner USING/WITH CHECK, authenticated DML only. Existing patient_profiles.display_name is reused, with no new profile table. Notes are not linked to an individual dose event yet (PARTIAL); optional medication association does not establish drug causality.

Summaries are generated on demand, not separately stored or scheduled. They read actual regimen versions/occurrences/reports and bounded notes; no invented historic denominator. Shared rollback SQL is static/disposable-only and has not been executed. Existing clinical table/confirmation guards unchanged.


## Actual evidence/gallery schema -> migrations015-018

This section describes applied implementation; the earlier broad target-table catalogue remains design guidance. No medication_products/product_ingredients/knowledge-vector table was added.

| Actual table / existing record | Implemented role |
|---|---|
| patient_medications | Owned identity anchor; display name and user-review status. |
| medication_evidence_tasks | Versioned bounded product evidence, separate product_missing fields, explicit printed_course_days, source IDs, missing regimen instructions, conflicts, duplicate candidates and draft regimen pointer. CAS task updates. |
| source_documents / source_fields | Original Printed.value/line extraction and separately reviewed regimen fields. Source kinds extended to package/pharmacy_label/prescription. |
| medication_source_links | Multiple owned source documents linked to one identity, with recorded timestamp. |
| regimen_versions | Separate historical/current courses; optional evidence_task_id owner FK and unique patient/task draft. Existing dates, PRN, food and schedule fields retained. |
| medication_images | Owned private object path/checksum/type/source association/review/eligibility. Loose pill, package, blister and source types kept separate. |
| visual_reference_sets / image_embeddings | Identity-linked model metadata and finite256-dimensional compatible embedding results. Stored bounded JSON; no new vector ANN index. |
| recognition_runs | Query task, selected regimen, actual references/outcome, independent decision/reason; safe_to_take=false and ingestion_proven=false. |

015 creates six new tables with PK/owned compositeFK/checks/indexes/FORCE RLS;016 adds typed tool allowlist and atomic SECURITY INVOKER reference commit;017 adds owner evidence-task activation guard and unique retry-safe draft link;018 adds tightly constrained logical reference retirement. Existing RLS/B14/storage safeguards remain. Rollback definitions exist but were not run on the shared development database.

Identity can exist without a regimen or gallery. Task conflict status prevents activation, and unresolved product-source conflict prevents interpreting a visual match as current-plan support. Packaging/blister references remain associated only. User review means patient-reviewed against supplied source, not clinician verification. Category is unknown or explicitly patient-entered POM/P/GSL/supplement; no HSA inference.

SourceEvidenceView extends the existing public SourceDocumentDTO with SourceLink.recorded_at and patient-provided origin. Review status/time stays the original persisted document metadata. Gallery exposes an owned evidence_task_id for source inspection and same-name warning counts; no automatic identity merge.

## 0.10.0 source evidence (2026-10-15)

No schema migration. Existing immutable source_documents.extraction_evidence retains the new printed instruction parts and original line, product release, list comparison and label classification. Existing medication_evidence_tasks.data retains the independent product, source ids, missing fields, conflicts and reviewable regimen proposal; medication_source_links and private medication_images retain each source. A code/strength/release or instruction conflict is persisted, never an overwrite. Existing same-user owner RLS applies. Optional recognition outcome imprint_check/imprint_read_for is retained in recognition_runs JSON; absent/unavailable reads do not prove matching. Existing JSON size limits remain unchanged.

## Reminder delivery migration021 (2026-10-15)

Reuse regimen_versions, dose_rules, dose_occurrences, dose_reminders and patient_profiles; no second medication schedule. Add reminders_enabled on profile; push_subscriptions binds owner/device endpoint/keys/enabled with eight-active-device limit. notification_deliveries binds owner/regimen/rule/occurrence/subscription, reminder instant, stable slot, pending/sending/sent/cancelled/failed state, attempts/backoff and scrubbed error category. Composite owner FKs and FORCE RLS preserve isolation. Authenticated patients have subscription SELECT/INSERT/UPDATE, delivery SELECT only; administrative worker alone claims/updates jobs. Migration and disposable-only rollback provided; no shared rollback/reset performed. Historical regimens/sources/events remain preserved.

## Additive migration024: dose evidence and optional conversations

202610160024_conversation_history.sql adds nullable source_documents.dose_basis and patient_profiles.conversation_history_enabled (default false), plus conversation_turns. Conversation rows have owner/session constraints, indexes and ENABLE/FORCE RLS. Same-user append/clear RPCs validate auth.uid; no new Agent or frontend privileged table access exists.

Saved history displays up to200 pairs from the last30days; pages are at most20. This is a read/RLS visibility window, not an independent timed physical purge. Supabase removes old/excess archive rows on a later successful append; inactive accounts can retain older text. The simulated memory adapter trims count and filters reads, without age-based physical cleanup. Explicit Clear removes the owner's archive and recent session text; it preserves clinical/task/challenge state. IDs are derived from session + client-turn ID to reject mismatched repeat writes. Source basis is immutable after review. Clinical facts, regimen versions, occurrences and dose events are separate and are not deleted with conversations. No scheduled deletion guarantee is made.

Migration024 was applied additively to the development Supabase after earlier ledger hashes were checked. Rollback is provided but intentionally refuses retained feature data; it was not executed. Do not edit applied forward SQL.

## Migration 025: conservative overlapping-plan restriction

`202610160025_regimen_overlap_guard.sql` adds a SECURITY INVOKER trigger; it does not delete, merge or rewrite existing records. It serializes same-patient draft/activation checks with an owned profile row lock. Matching known product IDs or normalized medication names cannot have overlapping active course dates; dose amount, PRN status and different medication-row IDs do not bypass the rule. The final day is inclusive and an unspecified end is open. The existing single-active-version-per-medication constraint remains stricter for versions of the same record.

The application checks before draft writes and rechecks on activation. Database SQLSTATE `P7501` maps to HTTP 409 `REGIMEN_OVERLAP`. Migration 025 was applied with owner authorization on 2026-10-16, together with its custom ledger entry; migrations001–024 were not replayed. Existing records were not rewritten. Rollback removes only the added trigger/function and requires separate approval.

This is an MVP representation restriction, **not a medical judgment** that same-name products, different doses or PRN plus scheduled instructions are inherently wrong. Reliable professional instructions may legitimately require combinations this MVP cannot represent. Exact normalized-name matching is conservative and does not establish ingredient/strength/form equivalence. Do not automatically stop, merge or delete existing plans. Explicitly ending an obsolete application record is distinct from advising a patient to stop taking medicine.

The opt-in `tests/backend/test_regimen_overlap_live.py` exercises real same-user JWT persistence, reviewed/B14 activation, conservative PRN conflicts, stop-and-replace, dose-event idempotency/history, independent concurrent Data API activations and cross-owner RLS. These are database/application checks, not hosted browser acceptance or evidence of clinical appropriateness. The concurrent transport gate synchronizes real requests and does not mock the provider response.
