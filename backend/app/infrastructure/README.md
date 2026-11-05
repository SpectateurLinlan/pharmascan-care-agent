# infrastructure

内存/SQL/HTTP/provider/存储适配，实现在 contracts 中定义的端口。

| 文件/子包 | 内容 |
|---|---|
| [care_repos.py](care_repos.py) | Long-term persistence through same-user JWT or explicit local test adapter. |
| [caregiver_repos.py](caregiver_repos.py) | Injected deterministic memory and same-user JWT/RLS contact adapters. |
| [clinical_memory.py](clinical_memory.py) | Shared read/write lock for staged, atomically published memory aggregates. |
| [conversation_history.py](conversation_history.py) | Same-user JWT history adapter and clearly simulated local adapter. |
| [conversation_threads.py](conversation_threads.py) | Injected memory and same-user JWT persistence; no privileged patient path. |
| [dispatch_process.py](dispatch_process.py) | Request-owned subprocess: hard timeout kills the worker, never detaches it. |
| [draft_deletion.py](draft_deletion.py) | Patient JWT SQL operation; storage cleanup uses the Storage API, not SQL. |
| [durable_agent_runs.py](durable_agent_runs.py) | Explicit memory/owner-JWT run control; never a remote mutable-lock facade. |
| [enrollment_operations.py](enrollment_operations.py) | SIMULATED transaction: no SQL, patient session, activation or clinical inference. |
| [evidence_images.py](evidence_images.py) | Patient-facing input errors around the existing strict image sanitizer. |
| [evidence_publication.py](evidence_publication.py) | Atomic simulated source publication. No SQL, provider calls or patient activation. |
| [evidence_repos.py](evidence_repos.py) | Normal same-user JWT artifacts and private image storage; no admin fallback. |
| [feedback_repos.py](feedback_repos.py) | In-memory tests and user-JWT/RLS feedback persistence. No admin fallback. |
| [gemini_model.py](gemini_model.py) | Official Google GenAI Interactions adapter; no retained Google conversation. |
| [identifiers.py](identifiers.py) | Production identifier adapter shared by HTTP and administrative composition roots. |
| [late_report_repos.py](late_report_repos.py) | Append-only patient report corrections; originals are never changed. |
| [library_files.py](library_files.py) | Patient-scoped PDF metadata persistence through the caller's Supabase JWT. |
| [memory_agent_runs.py](memory_agent_runs.py) | Process-local control records sharing the explicitly injected P04 boundary. |
| [memory_quota.py](memory_quota.py) | Deterministic in-memory accounting, with the same reservation semantics. |
| [memory_repos.py](memory_repos.py) | In-memory repositories implementing the Port protocols. |
| [memory_workflows.py](memory_workflows.py) | Isolated in-process workflow storage. Never a persistent-environment fallback. |
| [native_media_verification.py](native_media_verification.py) | Fixed owner-JWT native intent commands. No workflow, generic SQL or write retry. |
| [notification_jobs.py](notification_jobs.py) | Administrative scheduler adapter, never injected into patient HTTP. |
| [observation_repos.py](observation_repos.py) | Memory and same-user JWT health-note adapters. |
| [openfda_knowledge.py](openfda_knowledge.py) | Bounded public SPL lookup; exact product-family evidence, never a prescription. |
| [personal_vision.py](personal_vision.py) | Injected versioned contracts with independent embedding compatibility checks. |
| [plan_change_transactions.py](plan_change_transactions.py) | Atomic local plan-change review/activation; never a remote transaction claim. |
| [postgres_admin.py](postgres_admin.py) | Privileged administrative provisioning (admin setup only). |
| [postgres_db.py](postgres_db.py) | Postgres/Supabase connection handling. |
| [postgres_migrations.py](postgres_migrations.py) | Migration discovery, application and schema verification. |
| [postgres_repos.py](postgres_repos.py) | Real PostgreSQL/Supabase repository adapters. |
| [preference_repos.py](preference_repos.py) | Injected in-memory and same-JWT profile adapters. No admin fallback. |
| [push_subscriptions.py](push_subscriptions.py) | Same-user JWT only. Subscription secrets never appear in public responses. |
| [quota_repos.py](quota_repos.py) | User JWT calls only. No privileged database connection or editable counters. |
| [record_history.py](record_history.py) | Bounded same-user PostgREST reads and an explicitly synthetic memory adapter. |
| [reminder_repos.py](reminder_repos.py) | Implementations of the reminder preference port. |
| [source_gateway.py](source_gateway.py) | Reuse the versioned Stage2 label adapter with an owned per-call HTTP client. |
| [stage2_adapter.py](stage2_adapter.py) | v0.8.0 Stage2 anti-corruption adapter; fixtures are NOT model evaluation. |
| [stage2_http.py](stage2_http.py) | Injected bounded HTTP transport. No globals, redirects, secrets or POST retries. |
| [stage2_label_adapter.py](stage2_label_adapter.py) | Preferred /v1/read-label provider. Not a generic OCR or regimen service. |
| [stage2_schema.py](stage2_schema.py) | Versioned retained OpenAPI validation at the anti-corruption boundary. |
| [stage2_wire.py](stage2_wire.py) | Private infrastructure projections of retained v0.8/v0.10 schemas. |
| [supabase_data.py](supabase_data.py) | Request-scoped Supabase Data API transport. No administrative credentials. |
| [supabase_repos.py](supabase_repos.py) | User-token PostgREST implementations of the existing repository ports. |
| [tencent_speech.py](tencent_speech.py) | Bounded Tencent SentenceRecognition/TextToVoice adapter. |
| [verified_original_repos.py](verified_original_repos.py) | Explicit memory proof model and owner-JWT original commands; no remote mutex facade. |
| [vision_contracts.py](vision_contracts.py) | Compatibility imports for existing callers; public DTOs live in contracts. |
| [visual_gateway.py](visual_gateway.py) | Reuse the injected versioned strict adapter, owned client and validated image processing. |
| [web_push.py](web_push.py) | RFC Web Push adapter. No provider body, endpoint or key is logged. |
| [workflow_care_writes.py](workflow_care_writes.py) | Actual local care transactions; persistent owner RPC is separately composed. |
| [workflow_conversation_transactions.py](workflow_conversation_transactions.py) | One fixed same-JWT RPC, returning actual native rows instead of cached bodies. |
| [workflow_media_cleanup.py](workflow_media_cleanup.py) | Local native deletion fences and atomic acknowledgement; no Storage I/O here. |
| [workflow_media_storage.py](workflow_media_storage.py) | Local technical copy tickets; no clinical service or registration in verifier. |
| [workflow_media_writes.py](workflow_media_writes.py) | Explicit local media metadata transactions; external Storage is never rolled back. |
| [workflow_medication_writes.py](workflow_medication_writes.py) | Coupled native memory transactions. Patient SQL composition is separately gated. |
| [workflow_message_repos.py](workflow_message_repos.py) | Fixed conversation transactions; recording tests do not prove real SQL. |
| [workflow_notification_transactions.py](workflow_notification_transactions.py) | Fixed same-JWT subscription RPC. No sending or verifier authority. |
| [workflow_objects.py](workflow_objects.py) | Request-scoped owner-JWT immutable objects. Provisioning is deliberately external. |
| [workflow_record_writes.py](workflow_record_writes.py) | Explicit local native report transaction; no persistent callback fallback. |
| [workflow_reminder_writes.py](workflow_reminder_writes.py) | Native reminder transactions; no sender, subscription or schedule repository. |
| [workflow_repos.py](workflow_repos.py) | Fixed owner-JWT workflow commands. Not composed until SQL acceptance is approved. |
| [workflow_settings_writes.py](workflow_settings_writes.py) | Owned local profile/contact/feedback publication with minimal workflow receipts. |
| [workflow_verification.py](workflow_verification.py) | Lazy, fixed-command evidence connection; never a patient/admin repository. |

新增实现应留在本层职责内；依赖与信任边界以 docs/ARCHITECTURE.md 为准。
