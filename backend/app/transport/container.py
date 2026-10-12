"""Composition root for the HTTP transport.

This is the single place where concrete adapters are chosen and injected into
the application services. Routes receive an already-wired
``ApplicationContainer`` through FastAPI dependency injection, so no route
constructs a repository itself and no route can reach the database directly.

** SIMULATED **
The default container wires the in-memory fakes (B02: no PostgreSQL/Docker on
this machine). Every response that depends on them is labelled accordingly.
Swapping in a real Postgres adapter is a change to this file only.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ..agent.orchestrator import AgentOrchestrator, DeterministicIntentRouter
from ..agent.registry import ToolRegistry
from ..application.dosing import DoseScheduleService, SelfReportService
from ..application.enrollment import MedicationEnrollmentService
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


@dataclass
class ApplicationContainer:
    """Everything the routes need, already constructed and injected."""

    store: InMemoryStore
    clock: Clock
    ids: IdGenerator
    enrollment: MedicationEnrollmentService
    schedule: DoseScheduleService
    self_report: SelfReportService
    orchestrator: AgentOrchestrator
    registry: ToolRegistry


def build_container(
    *, clock: Clock | None = None, ids: IdGenerator | None = None
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

    enrollment = MedicationEnrollmentService(
        medications=medications,
        regimens=regimens,
        sources=sources,
        source_fields=source_fields,
        dose_rules=dose_rules,
        challenges=challenges,
        clock=the_clock,
        ids=the_ids,
    )
    schedule = DoseScheduleService(
        regimens=regimens,
        rules=dose_rules,
        occurrences=occurrences,
        clock=the_clock,
        ids=the_ids,
    )
    self_report = SelfReportService(
        regimens=regimens,
        medications=medications,
        occurrences=occurrences,
        events=events,
        clock=the_clock,
        ids=the_ids,
    )
    registry = ToolRegistry(
        enrollment=enrollment,
        schedule=schedule,
        self_report=self_report,
        traces=traces,
        clock=the_clock,
        ids=the_ids,
    )
    orchestrator = AgentOrchestrator(
        registry=registry,
        sessions=sessions,
        router=DeterministicIntentRouter(),
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
