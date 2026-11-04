"""Composition root for the HTTP transport.

This is the single place where concrete adapters are chosen and injected into
the application services. Routes receive an already-wired
``ApplicationContainer`` through FastAPI dependency injection, so no route
constructs a repository itself and no route can reach the database directly.

Three wirings are available:

``build_container``
    ** SIMULATED ** in-memory fakes. Fast, deterministic, used by the unit
    suite and available when no database is configured.
``build_supabase_container``
    Normal persistent HTTP wiring: verified user's JWT, publishable key,
    request-scoped Data API repositories and database RLS. No DATABASE_URL.
``build_postgres_patient_container``
    Explicit administrative RLS diagnostics. The PostgreSQL adapters run
    as the dedicated ``pharmascan_patient`` role (``NOBYPASSRLS``) with
    ``auth.uid()`` derived from the verified identity, so the database's own RLS
    policies scope every patient statement
    (``supabase/migrations/202610130004_patient_rls_role.sql``). The privileged
    ``DATABASE_URL`` connection is still held, but only for admin setup.
``build_postgres_privileged_container``
    The real adapters over the privileged role (``rolbypassrls = true``).
    Retained for migrations, schema verification, maintenance and the evidence
    harness — **never** as the normal patient path.

In all cases the repository *Ports* and the application services are identical —
only this file changes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from .persistent_workflow_graph import PersistentWorkflowGraph

from ..agent.capabilities import build_capability_registry
from ..agent.conversation import ConversationService
from ..agent.model_tools import ModelTools
from ..agent.orchestrator import AgentOrchestrator, DeterministicIntentRouter
from ..agent.registry import ToolRegistry
from ..application.agent_execution import AgentExecutionService
from ..application.ai_quota import QuotaAgent
from ..application.assistant_capabilities.draft_recovery import DraftRecoveryAdapter
from ..application.assistant_capabilities.enrollment import EnrollmentAdapter
from ..application.assistant_capabilities.medication_management import MedicationManagementAdapter
from ..application.assistant_messages import AssistantMessageService
from ..application.assistant_workflows import WorkflowService
from ..application.caregivers import CaregiverService
from ..application.conversation_history import ConversationHistoryService
from ..application.conversation_threads import ConversationThreadService
from ..application.dosing import DoseScheduleService, SelfReportService
from ..application.draft_deletion import DraftDeletionService
from ..application.enrollment import MedicationEnrollmentService
from ..application.enrollment_operations import EnrollmentOperationService
from ..application.evidence_enrollment import EvidenceEnrollmentService
from ..application.late_reports import LateReportService
from ..application.library_files import MedicationLibraryFileService
from ..application.long_term import LongTermCareService
from ..application.medication_names import MedicationNameResolver
from ..application.medication_understanding import MedicationUnderstandingService
from ..application.observations import ObservationService
from ..application.patient_feedback import FeedbackService
from ..application.personal_gallery import PersonalGalleryService
from ..application.preferences import PreferenceService
from ..application.push_test import PushTestService
from ..application.record_history import RecordHistoryService
from ..application.reminder_alerts import ReminderAlertService
from ..application.reminder_plan import ReminderPlanService
from ..application.reminders import ReminderService
from ..application.review_summary import ReviewSummaryService
from ..application.source_operations import SourceEnrollmentOperationService
from ..application.source_preview import SourcePreviewService
from ..application.speech import SpeechService
from ..application.timezone import PreferenceTzProvider
from ..application.visual_check import VisualCheckService
from ..application.workflow_attachments import WorkflowAttachmentService
from ..application.workflow_care import WorkflowCareService
from ..application.workflow_cleanup import ExistingSourceProtection, WorkflowCleanupService
from ..application.workflow_conversations import WorkflowConversationService
from ..application.workflow_enrollment_guard import WorkflowEnrollmentGuard
from ..application.workflow_image_compare import WorkflowImageCompareService
from ..application.workflow_knowledge import WorkflowKnowledgeService
from ..application.workflow_late_reports import WorkflowLateReportService
from ..application.workflow_media import WorkflowMediaService
from ..application.workflow_medication_transactions import MedicationWorkflowTransactions
from ..application.workflow_notifications import WorkflowNotificationService
from ..application.workflow_pdf_upload import WorkflowPdfUploadService
from ..application.workflow_photo_upload import WorkflowPhotoUploadService
from ..application.workflow_reminder_writes import WorkflowReminderWriteService
from ..application.workflow_reminders import WorkflowReminderReadService
from ..application.workflow_reports import WorkflowDoseReportService
from ..application.workflow_settings import WorkflowSettingsService
from ..application.workflow_source_preview import WorkflowSourcePreviewService
from ..config import Settings
from ..contracts.medication_evidence import PersonalVisionPort
from ..contracts.model import ConversationalModel
from ..contracts.ports import Clock, IdGenerator, PatientProvisioner
from ..contracts.push import PushSubscriptions
from ..contracts.reminders import ReminderRepository
from ..contracts.workflow_attachments import WorkflowAttachmentStore
from ..contracts.workflow_runtime import PersistentWorkflowPorts
from ..infrastructure.care_repos import MemoryCareRepository, SupabaseCareRepository
from ..infrastructure.caregiver_repos import MemoryCaregivers, SupabaseCaregivers
from ..infrastructure.conversation_history import MemoryConversationHistory, SupabaseConversationHistory
from ..infrastructure.conversation_threads import MemoryConversationThreads, SupabaseConversationThreads
from ..infrastructure.draft_deletion import MemoryDraftDeletion, SupabaseDraftDeletion
from ..infrastructure.enrollment_operations import InMemoryEnrollmentWritePort
from ..infrastructure.feedback_repos import MemoryFeedback, SupabaseFeedback
from ..infrastructure.identifiers import RandomIdGenerator
from ..infrastructure.late_report_repos import MemoryLateReports, SupabaseLateReports
from ..infrastructure.memory_agent_runs import MemoryRunRepository
from ..infrastructure.memory_repos import (
    InMemoryAgentSessionRepository,
    InMemoryConfirmationChallengeRepository,
    InMemoryDoseEventRepository,
    InMemoryDoseOccurrenceRepository,
    InMemoryDoseRuleRepository,
    InMemoryPatientMedicationRepository,
    InMemoryRegimenVersionRepository,
    InMemorySourceDocumentRepository,
    InMemorySourceFieldRepository,
    InMemoryStore,
    InMemoryToolTraceRepository,
    SequentialIdGenerator,
    SystemClock,
)
from ..infrastructure.memory_workflows import (
    MemoryActionRepository,
    MemoryCleanupRepository,
    MemoryControlRepository,
    MemoryOriginalRepository,
    MemoryWorkflowObjects,
    MemoryWorkflowRepository,
    MemoryWorkflowState,
)
from ..infrastructure.observation_repos import MemoryObservations, SupabaseObservations
from ..infrastructure.plan_change_transactions import MemoryPlanChangeReviewTransaction
from ..infrastructure.preference_repos import MemoryPreferences, SupabasePreferences
from ..infrastructure.quota_repos import SupabaseQuota
from ..infrastructure.record_history import MemoryRecordHistory, SupabaseRecordHistory
from ..infrastructure.reminder_repos import MemoryReminderRepository, SupabaseReminderRepository
from .auth import AuthBoundary, AuthenticatedPrincipal, SupabaseAuthApiVerifier

#: Honest labels for the trust boundary the patient repositories run under.
PATIENT_PATH_RLS = "rls_enforced_patient_role"
PATIENT_PATH_PRIVILEGED = "privileged_bypassrls"
PATIENT_PATH_SIMULATED = "simulated_in_memory"


@dataclass
class ApplicationContainer:
    """Everything the routes need, already constructed and injected."""

    store: InMemoryStore | None
    clock: Clock
    ids: IdGenerator
    enrollment: MedicationEnrollmentService
    schedule: DoseScheduleService
    self_report: SelfReportService
    orchestrator: AgentOrchestrator
    registry: ToolRegistry
    auth: AuthBoundary
    visual_check: VisualCheckService | None = None
    preferences: PreferenceService | None = None
    ai_agent: QuotaAgent | None = None
    conversational_model: ConversationalModel | None = None
    reminders: ReminderService | None = None
    reminder_alerts: ReminderAlertService | None = None
    reminder_plan: ReminderPlanService | None = None
    push_subscriptions: PushSubscriptions | None = None
    push_public_key: str | None = None
    push_test: PushTestService | None = None
    feedback: FeedbackService | None = None
    caregivers: CaregiverService | None = None
    observations: ObservationService | None = None
    review_summary: ReviewSummaryService | None = None
    long_term: LongTermCareService | None = None
    late_reports: LateReportService | None = None
    persistence: str = "simulated_in_memory"
    #: Which connection the patient repositories actually use. Reported by
    #: ``/api/health`` so the separation can be observed, not assumed.
    patient_data_path: str = PATIENT_PATH_SIMULATED
    #: Privileged admin setup (synthetic identity provisioning). ``None`` when
    #: no database is configured.
    admin: PatientProvisioner | None = None
    patient_factory: Callable[[AuthenticatedPrincipal], ApplicationContainer] | None = None
    speech: SpeechService | None = None
    source_preview: SourcePreviewService | None = None
    evidence_enrollment: EvidenceEnrollmentService | None = None
    gallery: PersonalGalleryService | None = None
    library_files: MedicationLibraryFileService | None = None
    close_request: Callable[[], None] | None = None
    draft_deletion: DraftDeletionService | None = None
    record_history: RecordHistoryService | None = None
    conversation_history: ConversationHistoryService | None = None
    conversation_threads: ConversationThreadService | None = None
    medication_understanding: MedicationUnderstandingService | None = None
    assistant_execution: AgentExecutionService | None = None
    assistant_workflows: WorkflowService | None = None
    assistant_transactions: PersistentWorkflowPorts | None = None
    assistant_candidate: PersistentWorkflowGraph | None = None
    assistant_medications: MedicationWorkflowTransactions | None = None
    assistant_attachments: WorkflowAttachmentService | None = None
    assistant_cleanup: WorkflowCleanupService | None = None
    assistant_sources: SourceEnrollmentOperationService | None = None
    assistant_reports: WorkflowDoseReportService | None = None
    assistant_late_reports: WorkflowLateReportService | None = None
    assistant_knowledge: WorkflowKnowledgeService | None = None
    assistant_care: WorkflowCareService | None = None
    assistant_media: WorkflowMediaService | None = None
    assistant_photo_upload: WorkflowPhotoUploadService | None = None
    assistant_pdf_upload: WorkflowPdfUploadService | None = None
    assistant_image_compare: WorkflowImageCompareService | None = None
    assistant_source_preview: WorkflowSourcePreviewService | None = None
    assistant_reminder_reads: WorkflowReminderReadService | None = None
    assistant_reminder_writes: WorkflowReminderWriteService | None = None
    assistant_notifications: WorkflowNotificationService | None = None
    assistant_notification_test_allowed: bool = False
    assistant_settings: WorkflowSettingsService | None = None
    assistant_feedback: WorkflowSettingsService | None = None
    assistant_conversations: WorkflowConversationService | None = None

    def messages(self) -> AssistantMessageService:
        return AssistantMessageService(
            orchestrator=self.orchestrator,
            handler=self.ai_agent,
            enrollment=self.enrollment,
            self_report=self.self_report,
            preferences=self.preferences,
            conversation_threads=self.conversation_threads,
            conversation_history=self.conversation_history,
            clock=self.clock,
            workflows=self.assistant_workflows,
            message_persistence=(
                self.assistant_transactions.messages
                if self.assistant_workflows and self.assistant_transactions
                else None
            ),
        )


def _services(
    *,
    medications,
    regimens,
    sources,
    source_fields,
    dose_rules,
    occurrences,
    events,
    sessions,
    challenges,
    traces,
    clock: Clock,
    ids: IdGenerator,
    reminder_repo: ReminderRepository | None = None,
    tz_provider=None,
    confirmation_guard=None,
):
    """Wire the application services over whichever repository set is given."""
    enrollment = MedicationEnrollmentService(
        tz_provider=tz_provider,
        confirmation_guard=confirmation_guard,
        medications=medications,
        regimens=regimens,
        sources=sources,
        source_fields=source_fields,
        dose_rules=dose_rules,
        occurrences=occurrences,
        events=events,
        challenges=challenges,
        clock=clock,
        ids=ids,
    )
    schedule = DoseScheduleService(
        tz_provider=tz_provider,
        regimens=regimens,
        rules=dose_rules,
        occurrences=occurrences,
        clock=clock,
        ids=ids,
    )
    self_report = SelfReportService(
        tz_provider=tz_provider,
        regimens=regimens,
        medications=medications,
        occurrences=occurrences,
        events=events,
        challenges=challenges,
        sessions=sessions,
        clock=clock,
        ids=ids,
    )
    reminders = (
        ReminderService(
            repository=reminder_repo,
            occurrences=occurrences,
            regimens=regimens,
            clock=clock,
            tz_provider=tz_provider,
            schedule=schedule,
        )
        if reminder_repo is not None
        else None
    )
    registry = ToolRegistry(
        reminders=reminders,
        enrollment=enrollment,
        schedule=schedule,
        self_report=self_report,
        traces=traces,
        clock=clock,
        ids=ids,
    )
    orchestrator = AgentOrchestrator(
        registry=registry,
        sessions=sessions,
        router=DeterministicIntentRouter(),
        clock=clock,
        ids=ids,
    )
    return enrollment, schedule, self_report, registry, orchestrator, reminders


def build_container(
    *,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
    auth: AuthBoundary | None = None,
    knowledge_v2_enabled: bool = False,
    assistant_workflows_enabled: bool = False,
    assistant_progress_enabled: bool = False,
    workflow_preview: SourcePreviewService | None = None,
    workflow_storage: WorkflowAttachmentStore | None = None,
    workflow_visual: VisualCheckService | None = None,
    workflow_personal_vision: PersonalVisionPort | None = None,
) -> ApplicationContainer:
    """Wire the whole application over a single in-memory store (SIMULATED)."""
    store = InMemoryStore()
    the_clock: Clock = clock or SystemClock()
    the_ids: IdGenerator = ids or SequentialIdGenerator()

    medications = InMemoryPatientMedicationRepository(store)
    regimens = InMemoryRegimenVersionRepository(store)
    sources = InMemorySourceDocumentRepository(store)
    source_fields = InMemorySourceFieldRepository(store)
    dose_rules = InMemoryDoseRuleRepository(store)
    occurrences = InMemoryDoseOccurrenceRepository(store)
    events = InMemoryDoseEventRepository(store)
    sessions = InMemoryAgentSessionRepository(store)
    challenges = InMemoryConfirmationChallengeRepository(store)
    traces = InMemoryToolTraceRepository(store)
    preference_repo = MemoryPreferences(rows={}, clock=the_clock, coordination=store.clinical)
    workflow_state = MemoryWorkflowState() if assistant_workflows_enabled else None
    workflow_tasks = MemoryWorkflowRepository(the_clock, state=workflow_state) if workflow_state else None
    workflow_controls = MemoryControlRepository(the_clock, state=workflow_state) if workflow_state else None
    enrollment_writer = InMemoryEnrollmentWritePort(store)
    workflow_actions = MemoryActionRepository(the_clock, state=workflow_state) if workflow_state else None
    confirmation_guard = (
        WorkflowEnrollmentGuard(
            bindings=enrollment_writer,
            tasks=workflow_tasks,
            controls=workflow_controls,
            actions=workflow_actions,
            transactions={"medication.plan.change": MemoryPlanChangeReviewTransaction(store)},
        )
        if workflow_tasks and workflow_controls
        else None
    )

    enrollment, schedule, self_report, registry, orchestrator, reminders = _services(
        confirmation_guard=confirmation_guard,
        tz_provider=PreferenceTzProvider(preference_repo),
        reminder_repo=MemoryReminderRepository(store),
        medications=medications,
        regimens=regimens,
        sources=sources,
        source_fields=source_fields,
        dose_rules=dose_rules,
        occurrences=occurrences,
        events=events,
        sessions=sessions,
        challenges=challenges,
        traces=traces,
        clock=the_clock,
        ids=the_ids,
    )

    from ..infrastructure.evidence_images import patient_reference_image, patient_source_image
    from ..infrastructure.evidence_repos import MemoryEvidenceRepository, MemoryImageStore
    from ..infrastructure.library_files import MemoryMedicationLibraryFiles

    evidence_repo = MemoryEvidenceRepository(medications, coordination=store.clinical)
    image_store = MemoryImageStore(coordination=store.clinical)
    from ..infrastructure.evidence_publication import MemoryEvidenceEnrollmentWritePort

    source_writer = (
        MemoryEvidenceEnrollmentWritePort(store, evidence_repo, image_store) if assistant_workflows_enabled else None
    )
    draft_deletion_port = MemoryDraftDeletion(store, evidence_repo, image_store)
    evidence_service = EvidenceEnrollmentService(
        source_writer=source_writer,
        repository=evidence_repo,
        medications=medications,
        sources=sources,
        fields=source_fields,
        enrollment=enrollment,
        preview=None,
        storage=image_store,
        normalize=patient_source_image,
        clock=the_clock,
        ids=the_ids,
    )
    gallery_service = PersonalGalleryService(
        repository=evidence_repo,
        storage=image_store,
        vision=workflow_personal_vision,
        enrollment=enrollment,
        normalize=patient_reference_image,
        clock=the_clock,
        ids=the_ids,
        tz_provider=PreferenceTzProvider(preference_repo),
    )
    library_files_service = MedicationLibraryFileService(
        repository=MemoryMedicationLibraryFiles(),
        storage=MemoryImageStore(coordination=store.clinical, bucket_id="medication-sources"),
        enrollment=enrollment,
        clock=the_clock,
        demo_only=True,
    )
    observations_service = ObservationService(MemoryObservations(), medications, the_clock)
    summary_service = ReviewSummaryService(enrollment, occurrences, events, observations_service, the_clock)
    long_term = LongTermCareService(
        MemoryCareRepository(), enrollment, events, observations_service, summary_service, the_clock, dose_rules
    )
    thread_repository = MemoryConversationThreads()

    from time import monotonic

    import httpx

    from ..infrastructure.openfda_knowledge import OpenFDAKnowledge

    knowledge_http = httpx.Client()
    medication_understanding = MedicationUnderstandingService(
        enrollment,
        OpenFDAKnowledge(knowledge_http, the_clock, monotonic=monotonic, scoped_facts=knowledge_v2_enabled),
        the_clock,
        name_resolver=MedicationNameResolver() if knowledge_v2_enabled else None,
    )

    def clear_chat_text(owner):
        sessions.clear_conversation_text(owner)
        thread_repository.clear(owner)

    root = ApplicationContainer(
        late_reports=LateReportService(
            enrollment=enrollment,
            schedule=schedule,
            events=events,
            repository=MemoryLateReports(store),
            challenges=challenges,
            clock=the_clock,
            ids=the_ids,
        ),
        draft_deletion=DraftDeletionService(draft_deletion_port, receipts=draft_deletion_port),
        record_history=RecordHistoryService(
            MemoryRecordHistory(store), enrollment, PreferenceService(preference_repo), the_clock
        ),
        conversation_threads=ConversationThreadService(
            thread_repository, sessions, the_clock, PreferenceService(preference_repo)
        ),
        conversation_history=ConversationHistoryService(MemoryConversationHistory(clear_chat_text), the_clock),
        long_term=long_term,
        medication_understanding=medication_understanding,
        close_request=knowledge_http.close,
        evidence_enrollment=evidence_service,
        gallery=gallery_service,
        library_files=library_files_service,
        observations=observations_service,
        review_summary=summary_service,
        preferences=PreferenceService(preference_repo),
        feedback=FeedbackService(MemoryFeedback({}), the_clock),
        caregivers=CaregiverService(MemoryCaregivers(), the_clock),
        reminder_plan=ReminderPlanService(
            medications=medications,
            regimens=regimens,
            schedule=schedule,
            events=events,
            reminders=reminders,
            clock=the_clock,
        ),
        reminder_alerts=ReminderAlertService(
            enrollment=enrollment,
            schedule=schedule,
            occurrences=occurrences,
            events=events,
            reminders=reminders,
            clock=the_clock,
        ),
        reminders=reminders,
        store=store,
        clock=the_clock,
        ids=the_ids,
        enrollment=enrollment,
        schedule=schedule,
        self_report=self_report,
        orchestrator=orchestrator,
        registry=registry,
        auth=auth or build_auth_boundary(settings=None),
        persistence="simulated_in_memory",
        speech=build_speech_service(settings=None, clock=the_clock, ids=the_ids),
    )
    if assistant_workflows_enabled:
        if assistant_progress_enabled:
            root.assistant_execution = AgentExecutionService(MemoryRunRepository(workflow_state))
        workflow_originals = MemoryOriginalRepository(
            state=workflow_state,
            tasks=workflow_tasks,
            controls=workflow_controls,
        )
        workflow_objects = (
            workflow_storage if workflow_storage is not None else MemoryWorkflowObjects(state=workflow_state)
        )
        workflow_cleanup = MemoryCleanupRepository(state=workflow_state)
        root.assistant_cleanup = WorkflowCleanupService(
            controls=workflow_controls,
            repository=workflow_cleanup,
            originals=workflow_originals,
            storage=workflow_objects,
            ids=the_ids,
            protection=ExistingSourceProtection(
                receipts=workflow_cleanup,
                enrollment=enrollment,
                tasks=workflow_tasks,
                actions=workflow_actions,
                enrollments=enrollment_writer,
                evidence=source_writer,
            ),
        )
        root.assistant_attachments = WorkflowAttachmentService(
            repository=workflow_originals,
            storage=workflow_objects,
            cleanup=root.assistant_cleanup,
            enrollment=enrollment,
            tasks=workflow_tasks,
            controls=workflow_controls,
            preferences=root.preferences,
            ids=the_ids,
            normalize=patient_source_image,
            preview=workflow_preview,
        )
        enrollment_operations = EnrollmentOperationService(enrollment, enrollment_writer)
        root.assistant_sources = SourceEnrollmentOperationService(
            evidence=root.evidence_enrollment,
            originals=root.assistant_attachments,
            tasks=workflow_tasks,
            controls=workflow_controls,
            operations=enrollment_operations,
        )
        enrollment_adapter = EnrollmentAdapter(
            enrollment,
            enrollment_operations,
            attachments=root.assistant_attachments,
        )
        from ..application.assistant_capabilities.plan_changes import PlanChangeAdapter

        plan_change_adapter = PlanChangeAdapter(enrollment, enrollment_operations, enrollment_adapter, workflow_tasks)
        from ..infrastructure.clinical_memory import MemoryClinicalMutationGuard

        management_adapter = MedicationManagementAdapter(
            enrollment,
            root.evidence_enrollment,
            workflow_actions,
            root.draft_deletion,
            MemoryClinicalMutationGuard(store.clinical),
        )
        recovery_adapter = DraftRecoveryAdapter(
            enrollment,
            enrollment_operations,
            enrollment_adapter,
            workflow_tasks,
            workflow_controls,
            MemoryClinicalMutationGuard(store.clinical),
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
            clinical=MemoryClinicalMutationGuard(store.clinical),
            clock=the_clock,
        )
        from ..application.assistant_capabilities.late_reports import PatientLateReportAdapter

        late_adapter = (
            PatientLateReportAdapter(
                reports=root.late_reports,
                actions=workflow_actions,
                clinical=MemoryClinicalMutationGuard(store.clinical),
            )
            if root.late_reports
            else None
        )
        late_adapters = dict.fromkeys(late_adapter.capability_ids, late_adapter) if late_adapter else {}
        from ..application.assistant_capabilities.knowledge import KnowledgeAdapter

        knowledge_resolver = MedicationNameResolver() if knowledge_v2_enabled else None
        knowledge_adapter = KnowledgeAdapter(resolver=knowledge_resolver) if knowledge_resolver else None
        from ..application.assistant_capabilities.care import CareAdapter

        care_adapter = (
            CareAdapter(
                enrollment=enrollment,
                observations=root.observations,
                care=root.long_term,
                clock=the_clock,
                actions=workflow_actions,
                clinical=MemoryClinicalMutationGuard(store.clinical),
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
            clinical=MemoryClinicalMutationGuard(store.clinical),
        )
        media_writers = dict.fromkeys(media_mutations.capability_ids, media_mutations)
        from ..application.assistant_capabilities.photo_upload import PhotoUploadAdapter

        photo_adapter = (
            PhotoUploadAdapter(
                enrollment=enrollment,
                gallery=root.gallery,
                attachments=root.assistant_attachments,
                actions=workflow_actions,
                clinical=MemoryClinicalMutationGuard(store.clinical),
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
                clinical=MemoryClinicalMutationGuard(store.clinical),
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
            clinical=MemoryClinicalMutationGuard(store.clinical),
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
            drafts=PreferenceDrafts(root.preferences),
            actions=workflow_actions,
            clinical=MemoryClinicalMutationGuard(store.clinical),
        )
        contact_adapter = SettingsMutationAdapter(
            drafts=ContactDrafts(root.caregivers),
            actions=workflow_actions,
            clinical=MemoryClinicalMutationGuard(store.clinical),
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
            drafts=FeedbackDrafts(root.feedback),
            actions=workflow_actions,
            clinical=MemoryClinicalMutationGuard(store.clinical),
        )
        settings_adapters = {
            **dict.fromkeys(preference_adapter.capability_ids, preference_adapter),
            **dict.fromkeys(contact_adapter.capability_ids, contact_adapter),
        }
        settings_writers = {key: adapter for key, adapter in settings_adapters.items() if key in adapter.write_ids}
        root.assistant_workflows = WorkflowService(
            repository=workflow_tasks,
            registry=build_capability_registry(),
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
        root.assistant_reports = WorkflowDoseReportService(workflows=root.assistant_workflows, adapter=report_adapter)
        root.assistant_image_compare = WorkflowImageCompareService(
            workflows=root.assistant_workflows,
            attachments=root.assistant_attachments,
            enrollment=enrollment,
            gallery=root.gallery,
            visual=workflow_visual,
            normalize=patient_source_image,
            clinical=MemoryClinicalMutationGuard(store.clinical),
        )
        root.assistant_source_preview = WorkflowSourcePreviewService(
            workflows=root.assistant_workflows,
            attachments=root.assistant_attachments,
            preview=workflow_preview,
            normalize=patient_source_image,
            clinical=MemoryClinicalMutationGuard(store.clinical),
        )
        root.assistant_reminder_reads = WorkflowReminderReadService(
            workflows=root.assistant_workflows,
            clinical=MemoryClinicalMutationGuard(store.clinical),
        )
        root.assistant_reminder_writes = WorkflowReminderWriteService(
            workflows=root.assistant_workflows, adapter=reminder_writer, preferences=root.preferences
        )
        root.assistant_notifications = WorkflowNotificationService(
            workflows=root.assistant_workflows, actions=workflow_actions, send_allowed=notification_allowed
        )
        root.assistant_settings = WorkflowSettingsService(
            workflows=root.assistant_workflows, adapters=settings_adapters, preferences=root.preferences
        )
        root.assistant_feedback = WorkflowSettingsService(
            workflows=root.assistant_workflows,
            adapters={"feedback.submit": feedback_adapter},
            preferences=root.preferences,
        )
        root.assistant_conversations = WorkflowConversationService(
            workflows=root.assistant_workflows,
            actions=workflow_actions,
            orchestrator=root.orchestrator,
            conversations=root.conversation_threads,
            history=root.conversation_history,
        )
        if pdf_adapter:
            root.assistant_pdf_upload = WorkflowPdfUploadService(
                workflows=root.assistant_workflows, adapter=pdf_adapter, preferences=root.preferences
            )
        if photo_adapter:
            root.assistant_photo_upload = WorkflowPhotoUploadService(
                workflows=root.assistant_workflows, adapter=photo_adapter, preferences=root.preferences
            )
        root.assistant_media = WorkflowMediaService(
            workflows=root.assistant_workflows, adapter=media_mutations, preferences=root.preferences
        )
        if late_adapter:
            root.assistant_late_reports = WorkflowLateReportService(
                workflows=root.assistant_workflows, adapter=late_adapter
            )
        if knowledge_resolver:
            root.assistant_knowledge = WorkflowKnowledgeService(
                workflows=root.assistant_workflows, understanding=medication_understanding, resolver=knowledge_resolver
            )
        if care_adapter:
            root.assistant_care = WorkflowCareService(
                workflows=root.assistant_workflows, adapter=care_adapter, preferences=root.preferences
            )
    return root


def _postgres_container(
    *,
    settings: Settings,
    repos,
    admin: PatientProvisioner | None,
    patient_data_path: str,
    clock: Clock | None,
    ids: IdGenerator | None,
) -> ApplicationContainer:
    """Wire the application services over an already-built Postgres bundle."""
    the_clock: Clock = clock or SystemClock()
    the_ids: IdGenerator = ids or SequentialIdGenerator()

    enrollment, schedule, self_report, registry, orchestrator, reminders = _services(
        medications=repos.medications,
        regimens=repos.regimens,
        sources=repos.sources,
        source_fields=repos.source_fields,
        dose_rules=repos.dose_rules,
        occurrences=repos.occurrences,
        events=repos.events,
        sessions=repos.sessions,
        challenges=repos.challenges,
        traces=repos.traces,
        clock=the_clock,
        ids=the_ids,
    )

    return ApplicationContainer(
        reminders=reminders,
        store=None,
        clock=the_clock,
        ids=the_ids,
        enrollment=enrollment,
        schedule=schedule,
        self_report=self_report,
        orchestrator=orchestrator,
        registry=registry,
        auth=build_auth_boundary(settings=settings),
        persistence="postgres",
        patient_data_path=patient_data_path,
        admin=admin,
    )


def build_postgres_patient_container(
    *,
    settings: Settings,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
) -> ApplicationContainer:
    """Administrative role-switch diagnostics; never serve patient HTTP.

    Imported lazily so the in-memory wiring never requires the database driver
    or a configured ``DATABASE_URL``.
    """
    from ..infrastructure.postgres_admin import PostgresAdminProvisioner
    from ..infrastructure.postgres_db import PostgresDatabase
    from ..infrastructure.postgres_repos import build_patient_rls_repositories

    database = PostgresDatabase(dsn=settings.require_database_url())
    repos = build_patient_rls_repositories(database)
    return _postgres_container(
        settings=settings,
        repos=repos,
        admin=PostgresAdminProvisioner(database),
        patient_data_path=PATIENT_PATH_RLS,
        clock=clock,
        ids=ids,
    )


def build_postgres_privileged_container(
    *,
    settings: Settings,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
) -> ApplicationContainer:
    """Admin/maintenance wiring over the privileged role (BYPASSRLS).

    Not for patient requests. Kept explicit so choosing it is a deliberate,
    reviewable act rather than a default.
    """
    from ..infrastructure.postgres_admin import PostgresAdminProvisioner
    from ..infrastructure.postgres_db import PostgresDatabase
    from ..infrastructure.postgres_repos import build_postgres_repositories

    database = PostgresDatabase(dsn=settings.require_database_url())
    repos = build_postgres_repositories(database)
    return _postgres_container(
        settings=settings,
        repos=repos,
        admin=PostgresAdminProvisioner(database),
        patient_data_path=PATIENT_PATH_PRIVILEGED,
        clock=clock,
        ids=ids,
    )


def build_auth_boundary(*, settings: Settings | None) -> AuthBoundary:
    """Choose the auth mode from configuration.

    ``AUTH_MODE=supabase`` requires the Supabase URL and publishable key so the
    Auth API can be called. Anything else is the anonymous demo principal, which
    is explicitly not authentication.
    """
    if settings is not None and settings.auth_mode not in ("supabase", "demo"):
        raise ValueError("Unsupported AUTH_MODE")
    if settings is not None and settings.auth_mode == "supabase":
        verifier = SupabaseAuthApiVerifier(
            supabase_url=settings.require_supabase_url(),
            api_key=settings.require_publishable_key(),
        )
        return AuthBoundary(mode="supabase", verifier=verifier)
    return AuthBoundary(mode="demo", demo_patient_id=demo_patient_id)


def build_container_from_settings(
    settings: Settings, *, clock: Clock | None = None, ids: IdGenerator | None = None
) -> ApplicationContainer:
    """Select the persistence adapter from configuration.

    ``PERSISTENCE=postgres`` requires ``DATABASE_URL`` and always selects the
    user-token Data API wiring and AUTH_MODE=supabase. No DATABASE_URL fallback.
    The default stays the
    in-memory wiring so an unconfigured checkout still runs.
    """
    if settings.persistence in ("postgres", "supabase"):
        return build_supabase_container(settings=settings, clock=clock, ids=ids)
    if settings.persistence != "in_memory":
        raise ValueError("Unsupported PERSISTENCE mode")
    visual = build_visual_check(settings=settings)
    source_preview_ids = ids or SequentialIdGenerator()
    preview = build_source_preview(settings=settings, ids=source_preview_ids)
    root = build_container(
        clock=clock,
        ids=source_preview_ids,
        auth=build_auth_boundary(settings=settings),
        knowledge_v2_enabled=settings.assistant_knowledge_v2_enabled,
        assistant_workflows_enabled=settings.assistant_workflows_enabled and settings.auth_mode == "demo",
        assistant_progress_enabled=settings.assistant_progress_enabled,
        workflow_visual=visual,
        workflow_preview=preview,
    )
    root.speech = build_speech_service(settings=settings, clock=root.clock, ids=root.ids)
    root.source_preview = preview
    root.visual_check = visual
    return root


def build_supabase_container(
    *,
    settings: Settings,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
) -> ApplicationContainer:
    """A persistent root has only a per-request user-token repository factory.

    DATABASE_URL is never inspected or used here. PostgreSQL factories remain
    available to explicit administrative scripts only.
    """
    from ..config import ConfigError
    from ..infrastructure.supabase_data import SupabaseDataClient
    from ..infrastructure.supabase_repos import build_supabase_repositories

    if settings.auth_mode != "supabase":
        raise ConfigError("Persistent patient access requires AUTH_MODE=supabase")
    base_url = settings.require_supabase_url()
    key = settings.require_publishable_key()
    auth = build_auth_boundary(settings=settings)
    root = build_container(clock=clock, ids=ids, auth=auth)
    if root.close_request is not None:
        root.close_request()
    root.close_request = None
    root.medication_understanding = None
    root.store = None
    root.persistence = "supabase"
    root.patient_data_path = "supabase_user_jwt_rls"
    push_key = None
    if settings.enable_push_subscriptions:
        from ..infrastructure.web_push import validate_vapid_public

        push_key = validate_vapid_public(settings.vapid_public_key)
    root.push_public_key = push_key
    root.speech = build_speech_service(settings=settings, clock=root.clock, ids=root.ids)
    root.source_preview = build_source_preview(settings=settings, ids=root.ids)
    root.visual_check = build_visual_check(settings=settings)
    if settings.model_provider == "gemini" and settings.gemini_api_key:
        from ..infrastructure.gemini_model import build_gemini_model

        root.conversational_model = build_gemini_model(key=settings.gemini_api_key, model=settings.gemini_model)

    import httpx

    # Load the verified trust store once per root, not twice per patient request.
    # Clients, connection pools and user credentials remain request-scoped.
    tls_context = httpx.create_ssl_context()

    def for_patient(principal: AuthenticatedPrincipal) -> ApplicationContainer:
        if not principal.authenticated or not principal.access_token:
            raise ConfigError("Verified user context required")
        http = httpx.Client(verify=tls_context)
        knowledge_http = httpx.Client(verify=tls_context)

        def close_request() -> None:
            http.close()
            knowledge_http.close()

        client = SupabaseDataClient(
            base_url=base_url,
            publishable_key=key,
            access_token=principal.access_token,
            patient_id=principal.patient_id,
            client=http,
        )
        preference_repo = SupabasePreferences(client)
        try:
            # Reuse this request's owned profile read. Provision only when absent,
            # rather than posting an unchanged profile on every patient read.
            from ..domain.errors import NotFoundError

            try:
                preference_repo.get(principal.patient_id)
            except NotFoundError:
                client.request(
                    "POST",
                    "/rest/v1/patient_profiles",
                    params={"on_conflict": "user_id"},
                    body={"user_id": str(principal.patient_id), "timezone": "Asia/Singapore", "demo_only": True},
                    prefer="resolution=ignore-duplicates,return=minimal",
                )
                preference_repo.get(principal.patient_id)
            repos = build_supabase_repositories(client, include_late_reports=settings.enable_late_dose_reports)
            services = _services(
                tz_provider=PreferenceTzProvider(preference_repo),
                reminder_repo=SupabaseReminderRepository(client),
                medications=repos.medications,
                regimens=repos.regimens,
                sources=repos.sources,
                source_fields=repos.source_fields,
                dose_rules=repos.dose_rules,
                occurrences=repos.occurrences,
                events=repos.events,
                sessions=repos.sessions,
                challenges=repos.challenges,
                traces=repos.traces,
                clock=root.clock,
                ids=ids or RandomIdGenerator(),
            )
            import json
            from pathlib import Path

            from ..infrastructure.evidence_images import patient_reference_image, patient_source_image
            from ..infrastructure.evidence_repos import SupabaseEvidenceRepository, SupabaseImageStore
            from ..infrastructure.library_files import SupabaseMedicationLibraryFiles
            from ..infrastructure.personal_vision import PersonalVisionGateway
            from ..infrastructure.stage2_schema import Stage2Contract

            evidence_repo = SupabaseEvidenceRepository(client, repos.medications)
            image_store = SupabaseImageStore(
                base_url=base_url,
                publishable_key=key,
                access_token=principal.access_token,
                patient_id=principal.patient_id,
            )
            pdf_store = SupabaseImageStore(
                base_url=base_url,
                publishable_key=key,
                access_token=principal.access_token,
                patient_id=principal.patient_id,
                bucket_id="medication-sources",
                content_type="application/pdf",
            )
            vision = None
            if settings.vision_api_base_url:
                snapshot = Path(__file__).resolve().parents[3] / "docs/external/pharmascan-api-openapi-0.10.0.json"
                vision = PersonalVisionGateway(
                    base_url=settings.vision_api_base_url,
                    contract=Stage2Contract(json.loads(snapshot.read_text(encoding="utf-8"))),
                )
            transactions = None
            if settings.assistant_workflows_enabled or settings.assistant_native_media_enabled:
                from .persistent_workflow_composition import build_persistent_workflow_ports

                transactions = build_persistent_workflow_ports(
                    data=client, evidence_dsn=settings.assistant_evidence_dsn
                )

            def native_media_services(image_storage, pdf_storage):
                evidence_service = EvidenceEnrollmentService(
                    repository=evidence_repo,
                    medications=repos.medications,
                    sources=repos.sources,
                    fields=repos.source_fields,
                    enrollment=services[0],
                    preview=root.source_preview,
                    storage=image_storage,
                    normalize=patient_source_image,
                    clock=root.clock,
                    ids=ids or RandomIdGenerator(),
                )
                gallery_service = PersonalGalleryService(
                    repository=evidence_repo,
                    storage=image_storage,
                    vision=vision,
                    enrollment=services[0],
                    normalize=patient_reference_image,
                    clock=root.clock,
                    ids=ids or RandomIdGenerator(),
                    tz_provider=PreferenceTzProvider(preference_repo),
                )
                library_files_service = (
                    MedicationLibraryFileService(
                        repository=SupabaseMedicationLibraryFiles(client),
                        storage=pdf_storage,
                        enrollment=services[0],
                        clock=root.clock,
                    )
                    if settings.enable_medication_library_files
                    else None
                )
                return evidence_service, gallery_service, library_files_service

            native_image_store, native_pdf_store = image_store, pdf_store
            if settings.assistant_native_media_enabled:
                from ..application.native_media_verification import VerifiedNativeMediaStore
                from ..infrastructure.native_media_verification import SupabaseNativeMediaIntents

                native_intents = SupabaseNativeMediaIntents(client)
                native_image_store = VerifiedNativeMediaStore(
                    owner=principal.patient_id,
                    storage=image_store,
                    intents=native_intents,
                    verifier=transactions.verifier,
                    clock=root.clock,
                )
                native_pdf_store = VerifiedNativeMediaStore(
                    owner=principal.patient_id,
                    storage=pdf_store,
                    intents=native_intents,
                    verifier=transactions.verifier,
                    clock=root.clock,
                )
            evidence_service, gallery_service, library_files_service = native_media_services(
                native_image_store, native_pdf_store
            )
            observations_service = ObservationService(SupabaseObservations(client), repos.medications, root.clock)
            summary_service = ReviewSummaryService(
                services[0], repos.occurrences, repos.events, observations_service, root.clock
            )
            long_term = LongTermCareService(
                SupabaseCareRepository(
                    client,
                    extended_tasks=settings.enable_care_task_followups,
                    multiple_reminders=settings.enable_multiple_care_reminders,
                ),
                services[0],
                repos.events,
                observations_service,
                summary_service,
                root.clock,
                repos.dose_rules,
            )
            from time import monotonic

            from ..infrastructure.openfda_knowledge import OpenFDAKnowledge

            medication_understanding = MedicationUnderstandingService(
                services[0],
                OpenFDAKnowledge(
                    knowledge_http,
                    root.clock,
                    monotonic=monotonic,
                    scoped_facts=settings.assistant_knowledge_v2_enabled,
                ),
                root.clock,
                name_resolver=MedicationNameResolver() if settings.assistant_knowledge_v2_enabled else None,
            )
            ai_agent = None
            if root.conversational_model:
                conversation = ConversationService(
                    model=root.conversational_model,
                    tools=ModelTools(
                        registry=services[3],
                        fallback=services[4],
                        visual_check=root.visual_check,
                        enrollment=services[0],
                        observations=observations_service,
                        evidence_enrollment=evidence_service,
                        long_term=long_term,
                        medication_understanding=medication_understanding,
                        timezone=preference_repo.get(principal.patient_id).timezone,
                        clock=root.clock,
                    ),
                    fallback=services[4],
                    sessions=repos.sessions,
                    ids=ids or RandomIdGenerator(),
                )
                ai_agent = QuotaAgent(
                    repository=SupabaseQuota(client),
                    conversation=conversation,
                    fallback=services[4],
                    daily_limit=settings.demo_agent_daily_turn_limit,
                )
            from ..infrastructure.push_subscriptions import SupabasePushSubscriptions

            scoped = ApplicationContainer(
                assistant_transactions=transactions if settings.assistant_workflows_enabled else None,
                late_reports=(
                    LateReportService(
                        enrollment=services[0],
                        schedule=services[1],
                        events=repos.events,
                        repository=SupabaseLateReports(client),
                        challenges=repos.challenges,
                        clock=root.clock,
                        ids=root.ids,
                    )
                    if settings.enable_late_dose_reports
                    else None
                ),
                draft_deletion=DraftDeletionService(SupabaseDraftDeletion(client, native_image_store)),
                record_history=RecordHistoryService(
                    SupabaseRecordHistory(client, include_late_reports=settings.enable_late_dose_reports),
                    services[0],
                    PreferenceService(preference_repo),
                    root.clock,
                ),
                conversation_threads=ConversationThreadService(
                    SupabaseConversationThreads(client), repos.sessions, root.clock, PreferenceService(preference_repo)
                ),
                conversation_history=ConversationHistoryService(SupabaseConversationHistory(client), root.clock),
                long_term=long_term,
                push_subscriptions=SupabasePushSubscriptions(client),
                push_public_key=push_key,
                push_test=root.push_test,
                evidence_enrollment=evidence_service,
                gallery=gallery_service,
                library_files=library_files_service,
                observations=observations_service,
                review_summary=summary_service,
                ai_agent=ai_agent,
                feedback=FeedbackService(SupabaseFeedback(client), root.clock),
                caregivers=CaregiverService(SupabaseCaregivers(client), root.clock),
                reminder_plan=ReminderPlanService(
                    medications=repos.medications,
                    regimens=repos.regimens,
                    schedule=services[1],
                    events=repos.events,
                    reminders=services[5],
                    clock=root.clock,
                ),
                reminder_alerts=ReminderAlertService(
                    enrollment=services[0],
                    schedule=services[1],
                    occurrences=repos.occurrences,
                    events=repos.events,
                    reminders=services[5],
                    clock=root.clock,
                ),
                preferences=PreferenceService(preference_repo),
                medication_understanding=medication_understanding,
                close_request=close_request,
                reminders=services[5],
                store=None,
                clock=root.clock,
                ids=ids or RandomIdGenerator(),
                enrollment=services[0],
                schedule=services[1],
                self_report=services[2],
                registry=services[3],
                orchestrator=services[4],
                auth=auth,
                persistence="supabase",
                patient_data_path="supabase_user_jwt_rls",
                speech=root.speech,
                source_preview=root.source_preview,
                visual_check=root.visual_check,
                conversational_model=root.conversational_model,
            )
            if settings.assistant_workflows_enabled and transactions is not None:
                from ..infrastructure.workflow_objects import (
                    LazyWorkflowObjects,
                    SupabaseWorkflowObjectAccess,
                    SupabaseWorkflowObjects,
                    WorkflowObjectAccess,
                )
                from .persistent_workflow_graph import build_persistent_workflow_graph

                objects = LazyWorkflowObjects(
                    lambda: SupabaseWorkflowObjects(
                        owner=principal.patient_id,
                        base_url=base_url,
                        bucket="medication-sources",
                        publishable_key=key,
                        access_token=principal.access_token,
                        client=http,
                        access=WorkflowObjectAccess(permit=SupabaseWorkflowObjectAccess(client).permit),
                    )
                )
                scoped.assistant_candidate = build_persistent_workflow_graph(
                    scoped=scoped,
                    ports=transactions,
                    data=client,
                    challenges=repos.challenges,
                    sessions=repos.sessions,
                    traces=repos.traces,
                    daily_limit=settings.demo_agent_daily_turn_limit,
                    objects=objects,
                    native_media_factory=native_media_services,
                    image_store=image_store,
                    pdf_store=pdf_store,
                    knowledge_v2_enabled=settings.assistant_knowledge_v2_enabled,
                )
            return scoped
        except Exception:
            close_request()
            raise

    root.patient_factory = for_patient
    return root


def build_speech_service(*, settings: Settings | None, clock: Clock, ids: IdGenerator) -> SpeechService:
    from ..infrastructure.tencent_speech import (
        TencentRpcTransport,
        TencentSpeechProvider,
        UnavailableSpeechProvider,
    )

    if (
        settings is not None
        and settings.enable_speech
        and settings.tencent_speech_approved
        and settings.tencent_secret_id
        and settings.tencent_secret_key
        and settings.tencent_voice_type
    ):
        provider = TencentSpeechProvider(
            transport=TencentRpcTransport(
                secret_id=settings.tencent_secret_id,
                secret_key=settings.tencent_secret_key,
                clock=clock,
                site=settings.tencent_speech_site,
            ),
            ids=ids,
            voice_type=settings.tencent_voice_type,
        )
        return SpeechService(
            provider=provider,
            clock=clock,
            available=True,
            active_stt=settings.stt_provider == "tencent",
            active_tts=settings.tts_provider == "tencent",
        )
    return SpeechService(
        provider=UnavailableSpeechProvider(),
        clock=clock,
        available=False,
        active_stt=settings is not None and settings.stt_provider == "tencent",
    )


def build_source_preview(*, settings: Settings, ids: IdGenerator) -> SourcePreviewService | None:
    import json
    from pathlib import Path

    from ..infrastructure.source_gateway import SourceGateway
    from ..infrastructure.stage2_schema import Stage2Contract

    if not settings.vision_api_base_url:
        return None
    snapshot = Path(__file__).resolve().parents[3] / "docs/external/pharmascan-api-openapi-0.10.0.json"
    contract = Stage2Contract(json.loads(snapshot.read_text(encoding="utf-8")))
    gateway = SourceGateway(base_url=settings.vision_api_base_url, contract=contract)
    return SourcePreviewService(provider=gateway, routing=gateway, ids=ids)


def demo_patient_id(client_id: str) -> UUID:
    """Derive a stable synthetic patient id from a browser client id.

    Deterministic so a page reload resumes the same demo patient, but scoped
    to the client id so two visitors never share a record. This is demo
    identity only — NOT authentication.
    """
    import hashlib

    digest = hashlib.sha256(f"pharmascan-demo::{client_id}".encode()).digest()
    return UUID(bytes=digest[:16], version=4)


def build_visual_check(*, settings: Settings) -> VisualCheckService | None:
    import json
    from pathlib import Path

    from ..infrastructure.stage2_schema import Stage2Contract
    from ..infrastructure.visual_gateway import VisualGateway

    if not settings.vision_api_base_url:
        return None
    path = Path(__file__).resolve().parents[3] / "docs/external/pharmascan-api-openapi-0.10.0.json"
    return VisualCheckService(
        provider=VisualGateway(
            base_url=settings.vision_api_base_url, contract=Stage2Contract(json.loads(path.read_text(encoding="utf-8")))
        )
    )
