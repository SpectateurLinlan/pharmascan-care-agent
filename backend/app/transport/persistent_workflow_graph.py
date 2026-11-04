"""Complete request-local candidate. Construction never enables a live rollout."""

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from ..application.assistant_capabilities.media_drafts import MediaDrafts
from ..application.draft_deletion import DraftDeletionService
from ..application.workflow_care_transactions import CareWorkflowTransactions
from ..application.workflow_conversation_transactions import ConversationWorkflowTransactions
from ..application.workflow_media_cleanup import MediaCleanupVerificationService
from ..application.workflow_media_storage import MediaCopyVerificationService
from ..application.workflow_media_transactions import MediaWorkflowTransactions
from ..application.workflow_media_upload_transactions import MediaUploadWorkflowTransactions
from ..application.workflow_medication_preparation import MedicationWritePreparationService
from ..application.workflow_medication_transactions import MedicationWorkflowTransactions
from ..application.workflow_message_policy import MessagePersistencePolicy
from ..application.workflow_notification_transactions import NotificationWorkflowTransactions
from ..application.workflow_record_transactions import RecordWorkflowTransactions
from ..application.workflow_reminder_transactions import ReminderWorkflowTransactions
from ..application.workflow_settings_transactions import SettingsWorkflowTransactions
from ..application.workflow_source_materialization import SourceMaterializationService
from ..application.workflow_verification import WorkflowVerificationService
from ..contracts.ports import AgentSessionRepository, ConfirmationChallengeRepository, ToolTraceRepository
from ..contracts.workflow_attachments import WorkflowAttachmentStore
from ..contracts.workflow_medication_writes import MedicationWorkflowWritePort
from ..contracts.workflow_runtime import PersistentWorkflowPorts
from ..domain.errors import ProviderUnavailableError
from ..infrastructure.draft_deletion import SupabaseDraftDeletion, SupabaseDraftDeletionReceipts
from ..infrastructure.enrollment_operations import SupabaseEnrollmentWritePort
from ..infrastructure.evidence_images import patient_reference_image, patient_source_image
from ..infrastructure.evidence_repos import SupabaseImageStore
from ..infrastructure.supabase_data import SupabaseDataClient
from ..infrastructure.workflow_conversation_transactions import SupabaseConversationTransitions
from ..infrastructure.workflow_medication_writes import CoupledEnrollmentWritePort, SupabaseMedicationWorkflowWrites
from ..infrastructure.workflow_notification_transactions import SupabaseNotificationTransitions
from ..infrastructure.workflow_repos import SupabaseCleanupRepository

if TYPE_CHECKING:
    from .container import ApplicationContainer


@dataclass(frozen=True, repr=False)
class PersistentWorkflowGraph:
    container: "ApplicationContainer" = field(repr=False)
    ports: PersistentWorkflowPorts = field(repr=False)
    implemented_capabilities: frozenset[str]
    unavailable_capabilities: frozenset[str]
    rollout_ready: Literal[False] = False

    def __repr__(self):
        return "PersistentWorkflowGraph(request_scoped=True, rollout_ready=False)"


class PersistentReadFence:
    """Read generation only. Remote writes require their fixed typed transaction."""

    def __init__(self, writes: MedicationWorkflowWritePort):
        self.writes = writes

    def revision(self, owner: UUID) -> int:
        return self.writes.revision(owner)

    def run(self, *args, **kwargs):
        raise ProviderUnavailableError("Use the explicit patient transaction")


def build_persistent_workflow_graph(
    *,
    scoped: "ApplicationContainer",
    ports: PersistentWorkflowPorts,
    data: SupabaseDataClient,
    challenges: ConfirmationChallengeRepository,
    sessions: AgentSessionRepository,
    traces: ToolTraceRepository,
    objects: WorkflowAttachmentStore,
    native_media_factory,
    image_store: SupabaseImageStore,
    pdf_store: SupabaseImageStore,
    knowledge_v2_enabled: bool,
    daily_limit: int,
) -> PersistentWorkflowGraph:
    from . import container as native

    root = replace(scoped)
    root.assistant_candidate = None
    the_clock, the_ids = root.clock, root.ids
    enrollment, schedule = root.enrollment, root.schedule
    from ..application.native_media_verification import VerifiedNativeMediaStore
    from ..infrastructure.native_media_verification import SupabaseNativeMediaIntents
    native_intents = SupabaseNativeMediaIntents(data)
    native_images = VerifiedNativeMediaStore(owner=data.patient_id, storage=image_store, intents=native_intents,
        verifier=ports.verifier, clock=the_clock)
    native_pdfs = VerifiedNativeMediaStore(owner=data.patient_id, storage=pdf_store, intents=native_intents,
        verifier=ports.verifier, clock=the_clock)
    root.evidence_enrollment, root.gallery, root.library_files = native_media_factory(native_images, native_pdfs)
    root.draft_deletion = DraftDeletionService(
        SupabaseDraftDeletion(data, native_images), receipts=SupabaseDraftDeletionReceipts(data)
    )
    workflow_tasks, workflow_controls, workflow_actions = ports.tasks, ports.controls, ports.actions
    workflow_preview, workflow_visual = root.source_preview, root.visual_check
    native_writer = SupabaseEnrollmentWritePort(data)
    workflow_objects = objects
    cleanup_rows = SupabaseCleanupRepository(data)
    verification = (
        WorkflowVerificationService(
            repository=ports.originals, storage=objects, verifier=ports.verifier, clock=the_clock
        )
        if ports.verifier
        else None
    )
    root.assistant_cleanup = native.WorkflowCleanupService(
        controls=ports.controls,
        repository=cleanup_rows,
        originals=ports.originals,
        storage=None,
        ids=the_ids,
        protection=native.ExistingSourceProtection(
            receipts=cleanup_rows,
            enrollment=enrollment,
            tasks=ports.tasks,
            actions=ports.actions,
            enrollments=native_writer,
        ),
        verification=verification,
    )
    root.assistant_attachments = native.WorkflowAttachmentService(
        repository=ports.originals,
        storage=objects if verification else None,
        tasks=ports.tasks,
        controls=ports.controls,
        preferences=root.preferences,
        ids=the_ids,
        normalize=patient_source_image,
        preview=workflow_preview,
        cleanup=root.assistant_cleanup,
        enrollment=enrollment,
        verification=verification,
    )
    native_operations = native.EnrollmentOperationService(enrollment, native_writer)
    source_operations = native.SourceEnrollmentOperationService(
        evidence=root.evidence_enrollment,
        originals=root.assistant_attachments,
        tasks=ports.tasks,
        controls=ports.controls,
        operations=native_operations,
    )
    media_copiers, media_cleanup_services = {}, {}
    materializer = None
    if ports.verifier:
        copier_args = dict(
            tickets=ports.media_copies,
            originals=ports.originals,
            source_storage=objects,
            verifier=ports.verifier,
            clock=the_clock,
            normalize=patient_reference_image,
            source_normalize=patient_source_image,
        )
        source_copier = MediaCopyVerificationService(target_storage=image_store, **copier_args)
        materializer = SourceMaterializationService(
            operations=source_operations,
            originals=ports.originals,
            copies=ports.media_copies,
            copier=source_copier,
            domain=ports.medications,
        )
        media_copiers = {
            "gallery.photo.add": source_copier,
            "library.pdf.add": MediaCopyVerificationService(target_storage=pdf_store, **copier_args),
        }
        media_cleanup_services = {
            "gallery.photo.delete": MediaCleanupVerificationService(
                tickets=ports.media_cleanup, storage=image_store, verifier=ports.verifier, clock=the_clock
            ),
            "library.pdf.delete": MediaCleanupVerificationService(
                tickets=ports.media_cleanup, storage=pdf_store, verifier=ports.verifier, clock=the_clock
            ),
        }
    preparations = MedicationWritePreparationService(
        enrollment=enrollment,
        operations=native_operations,
        evidence=root.evidence_enrollment,
        source_materializer=materializer,
    )
    ports = replace(
        ports,
        medications=SupabaseMedicationWorkflowWrites(
            data=data, reads=native_writer, receipts=ports.receipts, preparations=preparations
        ),
    )
    root.assistant_transactions = ports
    root.registry = native.ToolRegistry(
        enrollment=enrollment,
        schedule=schedule,
        self_report=root.self_report,
        reminders=root.reminders,
        traces=traces,
        clock=the_clock,
        ids=the_ids,
        records=ports.records,
        workflow_tasks=ports.tasks,
    )
    root.orchestrator = native.AgentOrchestrator(
        registry=root.registry,
        sessions=sessions,
        router=native.DeterministicIntentRouter(),
        clock=the_clock,
        ids=the_ids,
        persistence=MessagePersistencePolicy(messages=ports.messages),
    )
    if root.conversational_model is not None:
        root.ai_agent = native.QuotaAgent(
            repository=native.SupabaseQuota(data),
            daily_limit=daily_limit,
            fallback=root.orchestrator,
            conversation=native.ConversationService(
                model=root.conversational_model,
                fallback=root.orchestrator,
                sessions=sessions,
                ids=the_ids,
                tools=native.ModelTools(
                    registry=root.registry,
                    fallback=root.orchestrator,
                    visual_check=root.visual_check,
                    enrollment=enrollment,
                    observations=root.observations,
                    evidence_enrollment=root.evidence_enrollment,
                    long_term=root.long_term,
                    medication_understanding=root.medication_understanding,
                    timezone=root.preferences.get(data.patient_id).timezone,
                    clock=the_clock,
                ),
            ),
        )
    enrollment_writer = CoupledEnrollmentWritePort(native=native_writer, writes=ports.medications, tasks=ports.tasks)
    clinical = PersistentReadFence(ports.medications)
    enrollment_operations = native.EnrollmentOperationService(enrollment, enrollment_writer)
    root.assistant_sources = native.SourceEnrollmentOperationService(
        evidence=root.evidence_enrollment,
        originals=root.assistant_attachments,
        tasks=workflow_tasks,
        controls=workflow_controls,
        operations=enrollment_operations,
    )
    enrollment_adapter = native.EnrollmentAdapter(
        enrollment, enrollment_operations, attachments=root.assistant_attachments
    )
    from ..application.assistant_capabilities.plan_changes import PlanChangeAdapter

    plan_change_adapter = PlanChangeAdapter(enrollment, enrollment_operations, enrollment_adapter, workflow_tasks)
    management_adapter = native.MedicationManagementAdapter(
        enrollment, root.evidence_enrollment, workflow_actions, root.draft_deletion, clinical
    )
    recovery_adapter = native.DraftRecoveryAdapter(
        enrollment,
        enrollment_operations,
        enrollment_adapter,
        workflow_tasks,
        workflow_controls,
        clinical,
        source_capabilities=frozenset({"medication.source.add", "medication.source.review"}),
        plan_change_enabled=True,
    )
    from ..application.assistant_capabilities.sources import SourceAdapter

    source_adapter = SourceAdapter(
        enrollment=enrollment,
        evidence=root.evidence_enrollment,
        enrollment_adapter=enrollment_adapter,
        operations=enrollment_operations,
        actions=workflow_actions,
        source_operations=root.assistant_sources,
    )
    from ..application.assistant_capabilities.records import RecordAdapter

    record_adapter = (
        RecordAdapter(
            enrollment=enrollment,
            schedule=root.schedule,
            reports=root.self_report,
            history=root.record_history,
            summary=root.review_summary,
            understanding=root.medication_understanding,
            clock=the_clock,
            preferences=root.preferences,
        )
        if root.record_history is not None and root.review_summary is not None
        else None
    )
    from ..application.assistant_capabilities.reports import PatientReportAdapter

    report_adapter = PatientReportAdapter(
        enrollment=enrollment,
        reports=root.self_report,
        schedule=root.schedule,
        actions=workflow_actions,
        clinical=clinical,
        clock=the_clock,
    )
    from ..application.assistant_capabilities.late_reports import PatientLateReportAdapter

    late_adapter = (
        PatientLateReportAdapter(reports=root.late_reports, actions=workflow_actions, clinical=clinical)
        if root.late_reports
        else None
    )
    late_adapters = dict.fromkeys(late_adapter.capability_ids, late_adapter) if late_adapter else {}
    from ..application.assistant_capabilities.knowledge import KnowledgeAdapter

    knowledge_resolver = native.MedicationNameResolver() if knowledge_v2_enabled else None
    knowledge_adapter = KnowledgeAdapter(resolver=knowledge_resolver) if knowledge_resolver else None
    from ..application.assistant_capabilities.care import CareAdapter

    care_adapter = (
        CareAdapter(
            enrollment=enrollment,
            observations=root.observations,
            care=root.long_term,
            clock=the_clock,
            actions=workflow_actions,
            clinical=clinical,
        )
        if root.observations and root.long_term
        else None
    )
    care_adapters = dict.fromkeys(care_adapter.capability_ids, care_adapter) if care_adapter else {}
    care_writers = dict.fromkeys(care_adapter.write_ids, care_adapter) if care_adapter else {}
    from ..application.assistant_capabilities.media import MediaAdapter

    media_adapter = MediaAdapter(enrollment=enrollment, gallery=root.gallery, library=root.library_files)
    media_adapters = dict.fromkeys(media_adapter.capability_ids, media_adapter)
    from ..application.assistant_capabilities.media_mutations import MediaMutationAdapter

    media_mutations = MediaMutationAdapter(
        enrollment=enrollment,
        gallery=root.gallery,
        library=root.library_files,
        actions=workflow_actions,
        clinical=clinical,
    )
    media_writers = dict.fromkeys(media_mutations.capability_ids, media_mutations)
    from ..application.assistant_capabilities.photo_upload import PhotoUploadAdapter

    photo_adapter = (
        PhotoUploadAdapter(
            enrollment=enrollment,
            gallery=root.gallery,
            attachments=root.assistant_attachments,
            actions=workflow_actions,
            clinical=clinical,
        )
        if root.gallery and root.assistant_attachments
        else None
    )
    photo_adapters = dict.fromkeys(photo_adapter.capability_ids, photo_adapter) if photo_adapter else {}
    from ..application.assistant_capabilities.pdf_upload import PdfUploadAdapter

    pdf_adapter = (
        PdfUploadAdapter(
            enrollment=enrollment,
            library=root.library_files,
            attachments=root.assistant_attachments,
            actions=workflow_actions,
            clinical=clinical,
        )
        if root.library_files and root.assistant_attachments
        else None
    )
    pdf_adapters = dict.fromkeys(pdf_adapter.capability_ids, pdf_adapter) if pdf_adapter else {}
    from ..application.assistant_capabilities.image_compare import ImageCompareAdapter

    compare_adapter = ImageCompareAdapter(enrollment=enrollment, attachments=root.assistant_attachments)
    from ..application.assistant_capabilities.source_preview import SourcePreviewAdapter

    preview_adapter = SourcePreviewAdapter(attachments=root.assistant_attachments)
    from ..application.assistant_capabilities.reminders import ReminderReadAdapter

    reminder_read = ReminderReadAdapter(
        enrollment=enrollment,
        schedule=schedule,
        reminders=root.reminders,
        plan=root.reminder_plan,
        care=root.long_term,
        preferences=root.preferences,
        clock=the_clock,
    )
    from ..application.assistant_capabilities.reminder_mutations import ReminderMutationAdapter

    reminder_writer = ReminderMutationAdapter(
        enrollment=enrollment,
        schedule=schedule,
        reminders=root.reminders,
        preferences=root.preferences,
        clock=the_clock,
        actions=workflow_actions,
        clinical=clinical,
    )
    reminder_writers = dict.fromkeys(reminder_writer.capability_ids, reminder_writer)
    from ..application.assistant_capabilities.notification_devices import NotificationDeviceAdapter

    def notification_allowed():
        return root.assistant_notification_test_allowed

    notification_adapter = NotificationDeviceAdapter(send_allowed=notification_allowed)
    from ..application.assistant_capabilities.accounts import SecureAccountAdapter
    from ..application.assistant_capabilities.contacts import ContactDrafts
    from ..application.assistant_capabilities.preferences import PreferenceDrafts
    from ..application.assistant_capabilities.settings_mutations import SettingsMutationAdapter

    preference_adapter = SettingsMutationAdapter(
        drafts=PreferenceDrafts(root.preferences), actions=workflow_actions, clinical=clinical
    )
    contact_adapter = SettingsMutationAdapter(
        drafts=ContactDrafts(root.caregivers), actions=workflow_actions, clinical=clinical
    )
    account_adapter = SecureAccountAdapter()
    from ..application.assistant_capabilities.conversations import ConversationAdapter
    from ..application.assistant_capabilities.feedback import FeedbackDrafts
    from ..application.assistant_capabilities.support import SupportAdapter

    conversation_adapter = ConversationAdapter(
        conversations=root.conversation_threads,
        usage=lambda owner: root.ai_agent.usage(owner) if root.ai_agent else None,
    )
    support_adapter = SupportAdapter(enrollment=enrollment, care=root.long_term)
    feedback_adapter = SettingsMutationAdapter(
        drafts=FeedbackDrafts(root.feedback), actions=workflow_actions, clinical=clinical
    )
    settings_adapters = {
        **dict.fromkeys(preference_adapter.capability_ids, preference_adapter),
        **dict.fromkeys(contact_adapter.capability_ids, contact_adapter),
    }
    settings_writers = {key: adapter for key, adapter in settings_adapters.items() if key in adapter.write_ids}
    settings_transactions = SettingsWorkflowTransactions(
        writes=ports.settings, tasks=ports.tasks, receipts=ports.receipts
    )
    reminder_transactions = ReminderWorkflowTransactions(
        writes=ports.reminders, tasks=ports.tasks, receipts=ports.receipts
    )
    care_transactions = (
        CareWorkflowTransactions(
            writes=ports.care,
            tasks=ports.tasks,
            receipts=ports.receipts,
            adapter=care_adapter,
            preferences=root.preferences,
            care=root.long_term,
        )
        if care_adapter
        else None
    )
    media_transactions = MediaWorkflowTransactions(
        writes=ports.media,
        tasks=ports.tasks,
        receipts=ports.receipts,
        drafts=MediaDrafts(enrollment=enrollment, gallery=root.gallery, library=root.library_files),
        preferences=root.preferences,
        cleanup_services=media_cleanup_services,
    )
    upload_transactions = MediaUploadWorkflowTransactions(
        writes=ports.media,
        tasks=ports.tasks,
        receipts=ports.receipts,
        originals=ports.originals,
        source_storage=workflow_objects,
        copies=ports.media_copies,
        copiers=media_copiers,
        normalize=patient_reference_image,
        preferences=root.preferences,
        enrollment=enrollment,
    )
    record_transactions = RecordWorkflowTransactions(
        writes=ports.records,
        tasks=ports.tasks,
        receipts=ports.receipts,
        adapters={**dict.fromkeys(report_adapter.capability_ids, report_adapter), **late_adapters},
        preferences=root.preferences,
        reports=root.self_report,
        late_reports=root.late_reports,
        orchestrator=root.orchestrator,
    )
    root.assistant_medications = MedicationWorkflowTransactions(
        writes=ports.medications,
        bindings=native_writer,
        tasks=ports.tasks,
        receipts=ports.receipts,
        adapter=enrollment_adapter,
        attachments=root.assistant_attachments,
        enrollment=enrollment,
        challenges=challenges,
        orchestrator=root.orchestrator,
        preferences=root.preferences,
        clock=the_clock,
        preparers={
            "medication.enroll": enrollment_adapter,
            "medication.plan.change": plan_change_adapter,
            "medication.draft.resume": recovery_adapter,
        },
        maintenance=management_adapter,
        deletion=root.draft_deletion,
        source_adapter=source_adapter,
    )
    coordinators = [
        settings_transactions,
        reminder_transactions,
        media_transactions,
        upload_transactions,
        record_transactions,
        root.assistant_medications,
    ]
    if care_transactions:
        coordinators.append(care_transactions)
    transactions = {cap: coordinator for coordinator in coordinators for cap in coordinator.capability_ids}
    root.assistant_workflows = native.WorkflowService(
        repository=workflow_tasks,
        registry=native.build_capability_registry(),
        mutations=ports.mutations,
        business_transactions=transactions,
        controls=workflow_controls,
        attachments=root.assistant_attachments,
        cleanup=root.assistant_cleanup,
        adapters={
            **dict.fromkeys(conversation_adapter.capability_ids, conversation_adapter),
            **dict.fromkeys(support_adapter.capability_ids, support_adapter),
            **dict.fromkeys(feedback_adapter.capability_ids, feedback_adapter),
            **settings_adapters,
            **dict.fromkeys(account_adapter.capability_ids, account_adapter),
            **dict.fromkeys(notification_adapter.capability_ids, notification_adapter),
            **reminder_writers,
            "image.compare": compare_adapter,
            "source.preview": preview_adapter,
            **dict.fromkeys(reminder_read.capability_ids, reminder_read),
            **media_adapters,
            **photo_adapters,
            **pdf_adapters,
            **media_writers,
            **care_adapters,
            **({"medication.knowledge": knowledge_adapter} if knowledge_adapter else {}),
            "medication.plan.change": plan_change_adapter,
            "medication.enroll": enrollment_adapter,
            "medication.draft.resume": recovery_adapter,
            **dict.fromkeys(management_adapter.capability_ids, management_adapter),
            **dict.fromkeys(source_adapter.capability_ids, source_adapter),
            **(dict.fromkeys(record_adapter.capability_ids, record_adapter) if record_adapter else {}),
            **dict.fromkeys(report_adapter.capability_ids, report_adapter),
            **late_adapters,
        },
        writers={
            **dict.fromkeys(feedback_adapter.write_ids, feedback_adapter),
            **settings_writers,
            **reminder_writers,
            **photo_adapters,
            **pdf_adapters,
            **media_writers,
            **care_writers,
            **late_adapters,
            **dict.fromkeys(report_adapter.capability_ids, report_adapter),
            "medication.plan.change": plan_change_adapter,
            "medication.enroll": enrollment_adapter,
            "medication.draft.resume": recovery_adapter,
            "medication.plan.end": management_adapter,
            "medication.draft.delete": management_adapter,
            **dict.fromkeys(source_adapter.capability_ids, source_adapter),
        },
        patient_guards={
            **dict.fromkeys(feedback_adapter.write_ids, feedback_adapter),
            **settings_writers,
            **reminder_writers,
            **photo_adapters,
            **pdf_adapters,
            **media_writers,
            **care_writers,
            **late_adapters,
            **dict.fromkeys(report_adapter.capability_ids, report_adapter),
            "medication.plan.change": recovery_adapter,
            "medication.draft.delete": management_adapter,
            "medication.draft.resume": recovery_adapter,
            "medication.enroll": recovery_adapter,
            **dict.fromkeys(source_adapter.capability_ids, recovery_adapter),
        },
        patient_results={
            **dict.fromkeys(feedback_adapter.write_ids, feedback_adapter),
            **settings_writers,
            **reminder_writers,
            **photo_adapters,
            **pdf_adapters,
            **media_writers,
            **care_writers,
            **late_adapters,
            **dict.fromkeys(source_adapter.capability_ids, source_adapter),
            **dict.fromkeys(report_adapter.capability_ids, report_adapter),
        },
        task_resumers={
            "medication.draft.resume": recovery_adapter,
            **dict.fromkeys(source_adapter.capability_ids, source_adapter),
        },
        clock=the_clock,
        ids=the_ids,
        conversations=root.conversation_threads,
        preferences=root.preferences,
    )
    root.assistant_reports = native.WorkflowDoseReportService(
        workflows=root.assistant_workflows, adapter=report_adapter, transactions=record_transactions
    )
    root.assistant_image_compare = native.WorkflowImageCompareService(
        workflows=root.assistant_workflows,
        attachments=root.assistant_attachments,
        enrollment=enrollment,
        gallery=root.gallery,
        visual=workflow_visual,
        normalize=patient_source_image,
        clinical=clinical,
    )
    root.assistant_source_preview = native.WorkflowSourcePreviewService(
        workflows=root.assistant_workflows,
        attachments=root.assistant_attachments,
        preview=workflow_preview,
        normalize=patient_source_image,
        clinical=clinical,
    )
    root.assistant_reminder_reads = native.WorkflowReminderReadService(
        workflows=root.assistant_workflows, clinical=clinical
    )
    root.assistant_reminder_writes = native.WorkflowReminderWriteService(
        workflows=root.assistant_workflows,
        adapter=reminder_writer,
        preferences=root.preferences,
        transactions=reminder_transactions,
    )
    root.assistant_notifications = native.WorkflowNotificationService(
        workflows=root.assistant_workflows,
        actions=workflow_actions,
        send_allowed=notification_allowed,
        transactions=NotificationWorkflowTransactions(port=SupabaseNotificationTransitions(data)),
    )
    root.assistant_settings = native.WorkflowSettingsService(
        workflows=root.assistant_workflows,
        adapters=settings_adapters,
        preferences=root.preferences,
        transactions=settings_transactions,
    )
    root.assistant_feedback = native.WorkflowSettingsService(
        workflows=root.assistant_workflows,
        adapters={"feedback.submit": feedback_adapter},
        preferences=root.preferences,
        transactions=settings_transactions,
    )
    root.assistant_conversations = native.WorkflowConversationService(
        workflows=root.assistant_workflows,
        actions=workflow_actions,
        orchestrator=root.orchestrator,
        conversations=root.conversation_threads,
        history=root.conversation_history,
        transactions=ConversationWorkflowTransactions(
            port=SupabaseConversationTransitions(data),
            tasks=ports.tasks,
            clock=the_clock,
            conversations=root.conversation_threads,
        ),
    )
    if pdf_adapter:
        root.assistant_pdf_upload = native.WorkflowPdfUploadService(
            workflows=root.assistant_workflows,
            adapter=pdf_adapter,
            preferences=root.preferences,
            transactions=upload_transactions,
        )
    if photo_adapter:
        root.assistant_photo_upload = native.WorkflowPhotoUploadService(
            workflows=root.assistant_workflows,
            adapter=photo_adapter,
            preferences=root.preferences,
            transactions=upload_transactions,
        )
    root.assistant_media = native.WorkflowMediaService(
        workflows=root.assistant_workflows,
        adapter=media_mutations,
        preferences=root.preferences,
        transactions=media_transactions,
    )
    if late_adapter:
        root.assistant_late_reports = native.WorkflowLateReportService(
            workflows=root.assistant_workflows, adapter=late_adapter, transactions=record_transactions
        )
    if knowledge_resolver:
        root.assistant_knowledge = native.WorkflowKnowledgeService(
            workflows=root.assistant_workflows, understanding=root.medication_understanding, resolver=knowledge_resolver
        )
    if care_adapter:
        root.assistant_care = native.WorkflowCareService(
            workflows=root.assistant_workflows,
            adapter=care_adapter,
            preferences=root.preferences,
            transactions=care_transactions,
        )

    root.assistant_execution = native.AgentExecutionService(
        control=ports.runs, verifier=ports.verifier or UnavailableRunVerifier()
    )
    implemented = root.assistant_workflows.implemented_capabilities()
    return PersistentWorkflowGraph(
        container=root,
        ports=ports,
        implemented_capabilities=implemented,
        unavailable_capabilities=frozenset(ports.boundaries) - implemented,
    )


class UnavailableRunVerifier:
    def record_run(self, command, *, timeout_seconds):
        raise ProviderUnavailableError("Independent execution verification is unavailable")
