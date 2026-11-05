# application

用例、服务与业务工作流；通过显式端口访问持久化和外部能力。

| 文件/子包 | 内容 |
|---|---|
| [agent_execution.py](agent_execution.py) | Bounded orchestration and cooperative cancellation, with no clinical authority. |
| [agent_runtime_metadata.py](agent_runtime_metadata.py) | Hashes and actual SDK usage only; never retain prompts or provider responses. |
| [ai_quota.py](ai_quota.py) | Reserve before model calls; count successful user turns only, not rounds. |
| `assistant_capabilities/` | 各类 Assistant 能力的独立适配器/字段状态机 |
| [assistant_explanations.py](assistant_explanations.py) | Truthful evidence derived from actual results, without raw tool vocabulary. |
| [assistant_messages.py](assistant_messages.py) | Single application entry for legacy and versioned Assistant messages. |
| [assistant_navigation.py](assistant_navigation.py) | Resolve navigation references through the enrollment public service. |
| [assistant_workflows.py](assistant_workflows.py) | Deterministic coordination; adapters never gain patient confirmation authority. |
| [calendar_export.py](calendar_export.py) | Bounded RFC5545 export; UTC instants preserve the schedule's DST conversion. |
| [caregivers.py](caregivers.py) | Owned contact management only. No notification, verification or sharing side effect. |
| [conversation_history.py](conversation_history.py) | Opt-in bounded chat retention, no tool execution or patient fact mutation. |
| [conversation_threads.py](conversation_threads.py) | Opt-in durable conversations; never replay historical tool/confirmation state. |
| [dosing.py](dosing.py) | Dose schedule generation, due-dose lookup and self-report recording. |
| [draft_deletion.py](draft_deletion.py) | The route cannot turn a delete into an unconfirmed/agent-proposed write. |
| [durable_agent_execution.py](durable_agent_execution.py) | Command-based execution; SQL owner/run fences guard actual persisted writes. |
| [enrollment.py](enrollment.py) | Medication enrollment & regimen activation use-case. |
| [enrollment_collection.py](enrollment_collection.py) | Bounded explicit field capture. Captured text is unreviewed patient input. |
| [enrollment_operations.py](enrollment_operations.py) | Idempotent unactivated draft preparation over the existing clinical use case. |
| [enrollment_preview.py](enrollment_preview.py) | Read-only partial collection; no source review, business draft or activation. |
| [evidence_enrollment.py](evidence_enrollment.py) | Progressive source reconciliation; OCR supplies evidence, patients review plans. |
| [late_reports.py](late_reports.py) | Audited late reporting is separate from Agent backfill and never creates doses. |
| [library_files.py](library_files.py) | Medication-associated original PDF storage; never extracts clinical instructions. |
| [long_term.py](long_term.py) | Patient-owned stock, reported barriers and medication-related follow-ups. |
| [media_collection.py](media_collection.py) | Bounded bilingual media entry phrases; selection remains an owned typed query. |
| [medication_facts.py](medication_facts.py) | Conservative reconciliation of complete quotes within explicit source scopes. |
| [medication_names.py](medication_names.py) | Bounded suggestions; approximate names never establish a drug identity. |
| [medication_presentation.py](medication_presentation.py) | Presentation of already validated knowledge; no new medical facts or retrieval. |
| [medication_understanding.py](medication_understanding.py) | Explain general label uses separately from current patient-reviewed instructions. |
| [native_media_verification.py](native_media_verification.py) | Verified storage for existing native APIs, without tasks, extra originals or callbacks. |
| [notification_dispatch.py](notification_dispatch.py) | One bounded application pass shared by administrative CLI and HTTP worker. |
| [notification_worker.py](notification_worker.py) | Bounded delivery processing; never invokes Gemini or records intake. |
| [observations.py](observations.py) | Explicit patient-confirmed health notes; no dose or regimen write port. |
| [patient_feedback.py](patient_feedback.py) | Store explicitly submitted feedback through an owned repository port. |
| [personal_gallery.py](personal_gallery.py) | Identity-grouped private images and calibrated provider evidence, separate from intake. |
| [preferences.py](preferences.py) | Explicit preference operations with no regimen or intake authority. |
| [printed_instructions.py](printed_instructions.py) | Review proposals from printed instructions; no clinical schedule inference. |
| [push_test.py](push_test.py) | Explicit owner-scoped diagnostic send; never consumes a clinical queue slot. |
| [record_collection.py](record_collection.py) | Bounded record entry phrases; filters and patient confirmation stay typed. |
| [record_history.py](record_history.py) | Read-only, bounded two-stream history. No schedule materialisation or dose writes. |
| [reminder_alerts.py](reminder_alerts.py) | Scheduled/snoozed alerts from reviewed occurrences and injected server time. |
| [reminder_plan.py](reminder_plan.py) | One deterministic projection for in-app reminders, calendar and push workers. |
| [reminders.py](reminders.py) | Persist an occurrence-bound snooze preference; never modify regimen/intake. |
| [review_summary.py](review_summary.py) | Read only actual regimen versions, generated occurrences, reports and feelings. |
| [source_operations.py](source_operations.py) | Patient-only source saves from the current owned, verified raw original. |
| [source_preview.py](source_preview.py) | Read-only extraction preview; source text never becomes dosing authority. |
| [speech.py](speech.py) | Bounded, ephemeral speech calls, with no autonomous medication actions. |
| [temporal_doses.py](temporal_doses.py) | Calendar reads through public services; preserve original occurrence ownership. |
| [timezone.py](timezone.py) | Timezone handling: UTC storage, patient IANA timezone display. |
| [today_attention.py](today_attention.py) | Current local-day attention read; creates no occurrences, reports or reminders. |
| [visual_check.py](visual_check.py) | Read-only selected-regimen visual check. No unsafe catalogue-to-reference promotion. |
| [workflow_attachments.py](workflow_attachments.py) | Retain allowed originals before extraction; decoded processing bytes are derived. |
| [workflow_care.py](workflow_care.py) | Original patient APIs with optional current workflow authority and typed input. |
| [workflow_care_transactions.py](workflow_care_transactions.py) | Independently confirmed care API requests share the native/task transaction. |
| [workflow_cleanup.py](workflow_cleanup.py) | Request-triggered cleanup; object completion and metadata revocation stay distinct. |
| [workflow_conversation_transactions.py](workflow_conversation_transactions.py) | Fixed native transitions replace remote Python write callbacks. |
| [workflow_conversations.py](workflow_conversations.py) | Native conversation receipts prevent duplicate session creation or destructive retries. |
| [workflow_enrollment_guard.py](workflow_enrollment_guard.py) | Independent enrollment APIs respect the current task and no-save fence. |
| [workflow_image_compare.py](workflow_image_compare.py) | Explicit consented processing; never saves visual results or clinical records. |
| [workflow_knowledge.py](workflow_knowledge.py) | Explicit source lookup; answers never become saved workflow payloads. |
| [workflow_late_reports.py](workflow_late_reports.py) | Optional task binding around independent historical patient APIs. |
| [workflow_media.py](workflow_media.py) | Optional Assistant binding for the existing independently confirmed patient APIs. |
| [workflow_media_cleanup.py](workflow_media_cleanup.py) | Delete only a claimed immutable native key; settle facts separately from I/O. |
| [workflow_media_storage.py](workflow_media_storage.py) | Observe source normalization and actual native bytes, never a storage ACK. |
| [workflow_media_transactions.py](workflow_media_transactions.py) | Typed patient media confirmations; native tombstones never prove physical cleanup. |
| [workflow_media_upload_transactions.py](workflow_media_upload_transactions.py) | Saved raw originals, verified native copies and independent patient registration. |
| [workflow_medication_preparation.py](workflow_medication_preparation.py) | Reuse native policy for request-memory DTOs; fixed SQL still authorizes every write. |
| [workflow_medication_transactions.py](workflow_medication_transactions.py) | Existing independent patient enrollment APIs over fixed medication transactions. |
| [workflow_message_policy.py](workflow_message_policy.py) | One explicit retention policy for tasks, chat/context and fallbacks. |
| [workflow_notification_transactions.py](workflow_notification_transactions.py) | A confirmed browser request, never a model-supplied subscription credential. |
| [workflow_notifications.py](workflow_notifications.py) | Current saved task binding around native device APIs, not an Agent executor. |
| [workflow_operations.py](workflow_operations.py) | Operation receipts and owned observation. This service has no write executor. |
| [workflow_pdf_upload.py](workflow_pdf_upload.py) | Current authority for independently confirmed native PDF library uploads. |
| [workflow_photo_upload.py](workflow_photo_upload.py) | Current task authority for the existing independently confirmed gallery upload API. |
| [workflow_record_transactions.py](workflow_record_transactions.py) | Patient-only report summaries/confirmation over fixed native transaction DTOs. |
| [workflow_reminder_transactions.py](workflow_reminder_transactions.py) | Bridge independently confirmed reminder APIs to their owned transaction. |
| [workflow_reminder_writes.py](workflow_reminder_writes.py) | Optional task binding around the original patient reminder APIs. |
| [workflow_reminders.py](workflow_reminders.py) | Optional current-task binding for native calendar reads, with no patient write. |
| [workflow_reports.py](workflow_reports.py) | Optional patient HTTP binding; neither this service nor tokens enter model tools. |
| [workflow_settings.py](workflow_settings.py) | Optional exact current-task binding for native profile/preference/contact writes. |
| [workflow_settings_transactions.py](workflow_settings_transactions.py) | Current settings reviews bridge patient HTTP and the typed domain transaction. |
| [workflow_source_materialization.py](workflow_source_materialization.py) | Pure source proposal plus independently verified native image; no clinical publication. |
| [workflow_source_preview.py](workflow_source_preview.py) | Explicit source evidence preview; no durable extraction or medication writes. |
| [workflow_verification.py](workflow_verification.py) | Actual Storage I/O and narrow technical proof are distinct from patient publication. |

新增实现应留在本层职责内；依赖与信任边界以 docs/ARCHITECTURE.md 为准。
