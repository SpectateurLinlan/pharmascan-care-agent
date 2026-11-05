# contracts

对外 DTO、Protocol 和状态枚举；跨组件交换明确类型。

| 文件/子包 | 内容 |
|---|---|
| [agent_context.py](agent_context.py) | Versioned short-lived context, not permanent patient facts or vector memory. |
| [agent_execution.py](agent_execution.py) | Content-free execution port. Cancellation can stop, never authorize, a write. |
| [assistant_capabilities.py](assistant_capabilities.py) | Closed capability discovery; no identity or write credentials in model inputs. |
| [assistant_explanations.py](assistant_explanations.py) | Content-minimal evidence steps rendered in the patient's language. |
| [assistant_workflows.py](assistant_workflows.py) | Public workflow inputs; identity and confirmation remain server-owned. |
| [care_calendar.py](care_calendar.py) | Read-only calendar projection contract. Source records remain authoritative. |
| [care_workflow.py](care_workflow.py) | Partial patient drafts; identity, confirmation and request IDs are not inputs. |
| [caregivers.py](caregivers.py) | Private patient-entered contacts, without caregiver identity or delivery authority. |
| [chat_photo.py](chat_photo.py) | Bounded client-relayed image evidence; never patient facts or write authority. |
| [context_bounds.py](context_bounds.py) | Shared persistence budget; text windows never become medical authority. |
| [conversation_history.py](conversation_history.py) | Patient-readable conversation records, separate from model context and clinical facts. |
| [conversation_threads.py](conversation_threads.py) | Durable patient text, separate from executable tool/session state. |
| [conversation_workflow.py](conversation_workflow.py) | Closed chat-support operations; history and device text grant no clinical authority. |
| [dose_display.py](dose_display.py) | Source-backed display arithmetic, never a dose recommendation. |
| [dose_report_workflow.py](dose_report_workflow.py) | A report workflow selects an owned plan, never the patient's confirmation. |
| [draft_deletion.py](draft_deletion.py) | Public, explicitly confirmed unfinished-registration operation. |
| [dto.py](dto.py) | Application-facing typed DTOs (Pydantic v2). |
| [enrollment_operations.py](enrollment_operations.py) | Typed unactivated aggregates and owner-scoped idempotent write boundary. |
| [enrollment_workflow.py](enrollment_workflow.py) | Partial enrollment inputs are collection, never reviewed clinical facts. |
| [enums.py](enums.py) | Explicit status enums mirroring the SQL CHECK constraints in |
| [image_comparison.py](image_comparison.py) | Closed image processing inputs and non-clinical, page-only evidence. |
| [knowledge_workflow.py](knowledge_workflow.py) | Explicit general education query, separate from workflow preparation. |
| [late_report_workflow.py](late_report_workflow.py) | Historical review selection only; patient report contents never enter tools. |
| [late_reports.py](late_reports.py) | Explicit patient confirmation of reports about existing scheduled occurrences. |
| [library_files.py](library_files.py) | Patient-owned binary files attached to an existing medication record. |
| [long_term.py](long_term.py) | Public long-term care DTOs. Patient identity is never a request argument. |
| [media_workflow.py](media_workflow.py) | Closed read-only media selections; no paths, URLs, consent or write authority. |
| [medication_dialogue.py](medication_dialogue.py) | Read-only, session/conversation-bound medication choices. Never write authority. |
| [medication_evidence.py](medication_evidence.py) | Patient-owned product evidence, progressive tasks and visual artifacts. |
| [medication_facts.py](medication_facts.py) | Quoted, scoped use evidence; never product verification or dosing authority. |
| [medication_knowledge.py](medication_knowledge.py) | Read-only knowledge boundary. No patient identity crosses the provider port. |
| [medication_management.py](medication_management.py) | Closed read inputs and patient-visible plan projections; no confirmation tokens. |
| [medication_names.py](medication_names.py) | Name suggestions are not verified patient medication identities. |
| [medication_plan_changes.py](medication_plan_changes.py) | Patient instruction changes only; identity, linkage and confirmation are derived. |
| [medication_records.py](medication_records.py) | Closed record queries: collection data never carries patient/write authority. |
| [medication_sources.py](medication_sources.py) | Collected source references only; patient review stays outside model input. |
| [model.py](model.py) | Ephemeral conversational provider port, without patient identity authority. |
| [native_media_verification.py](native_media_verification.py) | Task-independent native file facts. Never source identity or clinical authority. |
| [navigation_context.py](navigation_context.py) | Navigation is a scoped record reference, never a medical conclusion. |
| [notifications.py](notifications.py) | Worker interfaces are distinct from patient HTTP and Agent tools. |
| [observations.py](observations.py) | Patient descriptions are records, never diagnoses or medication instructions. |
| [patient_feedback.py](patient_feedback.py) | Bounded patient feedback; not a medical message or emergency channel. |
| [ports.py](ports.py) | Repository and provider Port protocols (interfaces). |
| [preferences.py](preferences.py) | Patient UX preferences; language is not a clinical regimen instruction. |
| [privacy.py](privacy.py) | Shared text minimisation; untrusted text stays data, never authority. |
| [push.py](push.py) | Typed patient subscription boundary. Endpoints are restricted to push providers. |
| [quota.py](quota.py) | Atomic success accounting with hidden per-turn reservation capability. |
| [record_history.py](record_history.py) | Patient-owned read-only history; never creates occurrences or reports. |
| [reference_eligibility.py](reference_eligibility.py) | Reference classes and evidence for deterministic visual eligibility. |
| [reminder_workflow.py](reminder_workflow.py) | Closed reminder read/export fields; no snooze, settings or sender authority. |
| [reminders.py](reminders.py) | Reminder preferences are separate from clinical schedules and intake. |
| [review_summary.py](review_summary.py) | Deterministic, explicitly scoped record summaries; no adherence inference. |
| [settings_workflow.py](settings_workflow.py) | Closed preference/contact drafts; account secrets never belong to a workflow. |
| [source_extraction.py](source_extraction.py) | Read-only source extraction boundary, no regimen writes or dose inference. |
| [source_preview_workflow.py](source_preview_workflow.py) | Read-only source preview never carries reviewed instructions or write authority. |
| [speech.py](speech.py) | Speech is an input/output capability; it has no medication write authority. |
| [temporal.py](temporal.py) | Pure calendar interpretation; unsupported dates never silently mean today. |
| [today_attention.py](today_attention.py) | 提供 TodayPlan、TodayAttention |
| [vision.py](vision.py) | Public application DTOs. No external JSON objects, clients or ORM entities. |
| [visual_check.py](visual_check.py) | Normalized visual evidence, never clinical authorization. |
| [workflow_attachments.py](workflow_attachments.py) | Private originals and extraction state are distinct from reviewed sources. |
| [workflow_care_writes.py](workflow_care_writes.py) | Closed independent patient care actions; review markers are not native rows. |
| [workflow_conversation_transactions.py](workflow_conversation_transactions.py) | Closed independently confirmed native conversation transition. |
| [workflow_coordination.py](workflow_coordination.py) | A domain transaction owns task advancement; orchestration never repeats it. |
| [workflow_media_cleanup.py](workflow_media_cleanup.py) | Correlated native deletion, distinct from a tombstone or raw-original proof. |
| [workflow_media_storage.py](workflow_media_storage.py) | Technical native-copy evidence, isolated from raw-original publication. |
| [workflow_media_writes.py](workflow_media_writes.py) | Independent typed media commands; metadata deletion is not Storage evidence. |
| [workflow_medication_writes.py](workflow_medication_writes.py) | Closed native medication transactions; preparation never substitutes confirmation. |
| [workflow_messages.py](workflow_messages.py) | Closed conversation transactions, separate from patient business commands. |
| [workflow_notification_transactions.py](workflow_notification_transactions.py) | Patient browser credentials stay outside model/workflow fields and receipts. |
| [workflow_persistence.py](workflow_persistence.py) | Typed persistence bindings are constraints, never independent confirmation. |
| [workflow_record_writes.py](workflow_record_writes.py) | Patient-confirmed native record commands; never an Agent backfill authority. |
| [workflow_reminder_writes.py](workflow_reminder_writes.py) | Independent reminder preferences only; no notification or schedule authority. |
| [workflow_run_control.py](workflow_run_control.py) | UTC durable run commands; worker observations have no clinical authority. |
| [workflow_runtime.py](workflow_runtime.py) | Explicit request-local ports. Component construction is not rollout readiness. |
| [workflow_settings_writes.py](workflow_settings_writes.py) | Closed nonsecret settings commands; no Auth, delivery or verification authority. |
| [workflow_verification.py](workflow_verification.py) | Ticket-bound external observations; no clinical data or owner authority. |

新增实现应留在本层职责内；依赖与信任边界以 docs/ARCHITECTURE.md 为准。
