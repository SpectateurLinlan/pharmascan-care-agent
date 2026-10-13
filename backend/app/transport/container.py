"""Composition root for the HTTP transport.

This is the single place where concrete adapters are chosen and injected into
the application services. Routes receive an already-wired
``ApplicationContainer`` through FastAPI dependency injection, so no route
constructs a repository itself and no route can reach the database directly.

Two wirings are available:

``build_container``
    ** SIMULATED ** in-memory fakes. Fast, deterministic, used by the unit
    suite and available when no database is configured.
``build_postgres_container``
    The real PostgreSQL/Supabase adapters (``app.infrastructure.postgres_repos``)
    over an explicitly injected ``PostgresDatabase``.

``build_container_from_settings`` picks between them from configuration. In both
cases the repository *Ports* and the application services are identical — only
this file changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ..agent.orchestrator import AgentOrchestrator, DeterministicIntentRouter
from ..agent.registry import ToolRegistry
from ..application.dosing import DoseScheduleService, SelfReportService
from ..application.enrollment import MedicationEnrollmentService
from ..config import Settings
from ..contracts.ports import Clock, IdGenerator
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
from .auth import AuthBoundary, SupabaseAuthApiVerifier


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
    persistence: str = "simulated_in_memory"


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
        clock=clock,
        ids=ids,
    )
    registry = ToolRegistry(
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
    return enrollment, schedule, self_report, registry, orchestrator


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

    enrollment, schedule, self_report, registry, orchestrator = _services(
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

    return ApplicationContainer(
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
    )


def build_postgres_container(
    *,
    settings: Settings,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
) -> ApplicationContainer:
    """Wire the application over the real PostgreSQL/Supabase adapters.

    Imported lazily so the in-memory wiring never requires the database driver
    or a configured ``DATABASE_URL``.
    """
    from ..infrastructure.postgres_db import PostgresDatabase
    from ..infrastructure.postgres_repos import build_postgres_repositories

    database = PostgresDatabase(dsn=settings.require_database_url())
    repos = build_postgres_repositories(database)
    the_clock: Clock = clock or SystemClock()
    the_ids: IdGenerator = ids or SequentialIdGenerator()

    enrollment, schedule, self_report, registry, orchestrator = _services(
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
    )


def build_auth_boundary(*, settings: Settings | None) -> AuthBoundary:
    """Choose the auth mode from configuration.

    ``AUTH_MODE=supabase`` requires the Supabase URL and publishable key so the
    Auth API can be called. Anything else is the anonymous demo principal, which
    is explicitly not authentication.
    """
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

    ``PERSISTENCE=postgres`` requires ``DATABASE_URL``. The default stays the
    in-memory wiring so an unconfigured checkout still runs.
    """
    if settings.persistence == "postgres":
        return build_postgres_container(settings=settings, clock=clock, ids=ids)
    return build_container(clock=clock, ids=ids, auth=build_auth_boundary(settings=settings))


def demo_patient_id(client_id: str) -> UUID:
    """Derive a stable synthetic patient id from a browser client id.

    Deterministic so a page reload resumes the same demo patient, but scoped
    to the client id so two visitors never share a record. This is demo
    identity only — NOT authentication.
    """
    import hashlib

    digest = hashlib.sha256(f"pharmascan-demo::{client_id}".encode()).digest()
    return UUID(bytes=digest[:16], version=4)
