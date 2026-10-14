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
from uuid import UUID, uuid4

from ..agent.conversation import ConversationService
from ..agent.model_tools import ModelTools
from ..agent.orchestrator import AgentOrchestrator, DeterministicIntentRouter
from ..agent.registry import ToolRegistry
from ..application.ai_quota import QuotaAgent
from ..application.caregivers import CaregiverService
from ..application.dosing import DoseScheduleService, SelfReportService
from ..application.enrollment import MedicationEnrollmentService
from ..application.evidence_enrollment import EvidenceEnrollmentService
from ..application.observations import ObservationService
from ..application.patient_feedback import FeedbackService
from ..application.personal_gallery import PersonalGalleryService
from ..application.preferences import PreferenceService
from ..application.reminder_alerts import ReminderAlertService
from ..application.reminders import ReminderService
from ..application.review_summary import ReviewSummaryService
from ..application.source_preview import SourcePreviewService
from ..application.speech import SpeechService
from ..application.visual_check import VisualCheckService
from ..config import Settings
from ..contracts.model import ConversationalModel
from ..contracts.ports import Clock, IdGenerator, PatientProvisioner
from ..contracts.reminders import ReminderRepository
from ..infrastructure.caregiver_repos import MemoryCaregivers, SupabaseCaregivers
from ..infrastructure.feedback_repos import MemoryFeedback, SupabaseFeedback
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
from ..infrastructure.observation_repos import MemoryObservations, SupabaseObservations
from ..infrastructure.preference_repos import MemoryPreferences, SupabasePreferences
from ..infrastructure.quota_repos import SupabaseQuota
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
    feedback: FeedbackService | None = None
    caregivers: CaregiverService | None = None
    observations: ObservationService | None = None
    review_summary: ReviewSummaryService | None = None
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
):
    """Wire the application services over whichever repository set is given."""
    enrollment = MedicationEnrollmentService(
        medications=medications,
        regimens=regimens,
        sources=sources,
        source_fields=source_fields,
        dose_rules=dose_rules,
        challenges=challenges,
        clock=clock,
        ids=ids,
    )
    schedule = DoseScheduleService(
        regimens=regimens,
        rules=dose_rules,
        occurrences=occurrences,
        clock=clock,
        ids=ids,
    )
    self_report = SelfReportService(
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
        ReminderService(repository=reminder_repo, occurrences=occurrences, regimens=regimens, clock=clock)
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

    enrollment, schedule, self_report, registry, orchestrator, reminders = _services(
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

    evidence_repo, image_store = MemoryEvidenceRepository(medications), MemoryImageStore()
    evidence_service = EvidenceEnrollmentService(
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
        vision=None,
        enrollment=enrollment,
        normalize=patient_reference_image,
        clock=the_clock,
        ids=the_ids,
    )
    observations_service = ObservationService(MemoryObservations(), medications, the_clock)
    return ApplicationContainer(
        evidence_enrollment=evidence_service,
        gallery=gallery_service,
        observations=observations_service,
        review_summary=ReviewSummaryService(enrollment, occurrences, events, observations_service, the_clock),
        preferences=PreferenceService(MemoryPreferences(rows={}, clock=the_clock)),
        feedback=FeedbackService(MemoryFeedback({}), the_clock),
        caregivers=CaregiverService(MemoryCaregivers(), the_clock),
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
    root = build_container(clock=clock, ids=ids, auth=build_auth_boundary(settings=settings))
    root.speech = build_speech_service(settings=settings, clock=root.clock, ids=root.ids)
    root.source_preview = build_source_preview(settings=settings, ids=root.ids)
    root.visual_check = build_visual_check(settings=settings)
    return root


class RandomIdGenerator:
    def new_id(self) -> UUID:
        return uuid4()


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
    root.store = None
    root.persistence = "supabase"
    root.patient_data_path = "supabase_user_jwt_rls"
    root.speech = build_speech_service(settings=settings, clock=root.clock, ids=root.ids)
    root.source_preview = build_source_preview(settings=settings, ids=root.ids)
    root.visual_check = build_visual_check(settings=settings)
    if settings.model_provider == "gemini" and settings.gemini_api_key:
        from ..infrastructure.gemini_model import build_gemini_model

        root.conversational_model = build_gemini_model(key=settings.gemini_api_key, model=settings.gemini_model)

    def for_patient(principal: AuthenticatedPrincipal) -> ApplicationContainer:
        if not principal.authenticated or not principal.access_token:
            raise ConfigError("Verified user context required")
        client = SupabaseDataClient(
            base_url=base_url, publishable_key=key, access_token=principal.access_token, patient_id=principal.patient_id
        )
        # Identity already exists in Auth; create only its own owner profile.
        client.request(
            "POST",
            "/rest/v1/patient_profiles",
            params={"on_conflict": "user_id"},
            body={"user_id": str(principal.patient_id), "timezone": "Asia/Singapore", "demo_only": True},
            prefer="resolution=ignore-duplicates,return=minimal",
        )
        repos = build_supabase_repositories(client)
        services = _services(
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
        from ..infrastructure.personal_vision import PersonalVisionGateway
        from ..infrastructure.stage2_schema import Stage2Contract

        evidence_repo = SupabaseEvidenceRepository(client, repos.medications)
        image_store = SupabaseImageStore(
            base_url=base_url, publishable_key=key, access_token=principal.access_token, patient_id=principal.patient_id
        )
        vision = None
        if settings.vision_api_base_url:
            snapshot = Path(__file__).resolve().parents[3] / "docs/external/pharmascan-api-openapi-0.8.0.json"
            vision = PersonalVisionGateway(
                base_url=settings.vision_api_base_url,
                contract=Stage2Contract(json.loads(snapshot.read_text(encoding="utf-8"))),
            )
        evidence_service = EvidenceEnrollmentService(
            repository=evidence_repo,
            medications=repos.medications,
            sources=repos.sources,
            fields=repos.source_fields,
            enrollment=services[0],
            preview=root.source_preview,
            storage=image_store,
            normalize=patient_source_image,
            clock=root.clock,
            ids=ids or RandomIdGenerator(),
        )
        gallery_service = PersonalGalleryService(
            repository=evidence_repo,
            storage=image_store,
            vision=vision,
            enrollment=services[0],
            normalize=patient_reference_image,
            clock=root.clock,
            ids=ids or RandomIdGenerator(),
        )
        observations_service = ObservationService(SupabaseObservations(client), repos.medications, root.clock)
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
        return ApplicationContainer(
            evidence_enrollment=evidence_service,
            gallery=gallery_service,
            observations=observations_service,
            review_summary=ReviewSummaryService(
                services[0], repos.occurrences, repos.events, observations_service, root.clock
            ),
            ai_agent=ai_agent,
            feedback=FeedbackService(SupabaseFeedback(client), root.clock),
            caregivers=CaregiverService(SupabaseCaregivers(client), root.clock),
            reminder_alerts=ReminderAlertService(
                enrollment=services[0],
                schedule=services[1],
                occurrences=repos.occurrences,
                events=repos.events,
                reminders=services[5],
                clock=root.clock,
            ),
            preferences=PreferenceService(SupabasePreferences(client)),
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
        )

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
    snapshot = Path(__file__).resolve().parents[3] / "docs/external/pharmascan-api-openapi-0.8.0.json"
    contract = Stage2Contract(json.loads(snapshot.read_text(encoding="utf-8")))
    return SourcePreviewService(
        provider=SourceGateway(base_url=settings.vision_api_base_url, contract=contract), ids=ids
    )


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
    path = Path(__file__).resolve().parents[3] / "docs/external/pharmascan-api-openapi-0.8.0.json"
    return VisualCheckService(
        provider=VisualGateway(
            base_url=settings.vision_api_base_url, contract=Stage2Contract(json.loads(path.read_text(encoding="utf-8")))
        )
    )
