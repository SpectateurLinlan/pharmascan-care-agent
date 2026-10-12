"""Shared test harness: deterministic clock, predictable ids, wired fakes.

Marked SIMULATED: this substitutes for PostgreSQL/Supabase (B02) and for a
real LLM provider (B03). It is never reported as a live integration test.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.application.dosing import DoseScheduleService, SelfReportService  # noqa: E402
from app.application.enrollment import MedicationEnrollmentService  # noqa: E402
from app.infrastructure.memory_repos import (  # noqa: E402
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
)

FIXED_NOW = datetime(2026, 10, 13, 1, 30, tzinfo=UTC)  # 09:30 Asia/Singapore


class FixedClock:
    """Deterministic clock; advance() moves time explicitly in tests."""

    def __init__(self, moment: datetime = FIXED_NOW) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment

    def advance(self, **kwargs: float) -> None:
        self._moment = self._moment + timedelta(**kwargs)


class CountingIdGenerator:
    """Predictable UUIDs so assertions can reference exact ids.

    Ids are drawn from a high range so they can never collide with the small
    integer UUIDs used as patient identifiers in the tests.
    """

    OFFSET = 1 << 96  # keeps generated ids far away from UUID(int=100) style ids

    def __init__(self, start: int = 1) -> None:
        self._next = start

    def new_id(self) -> UUID:
        value = self.OFFSET + self._next
        self._next += 1
        return UUID(int=value)


@pytest.fixture()
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture()
def clock() -> FixedClock:
    return FixedClock()


@pytest.fixture()
def wired(store: InMemoryStore, clock: FixedClock):
    """Fully wired application services over in-memory fakes (SIMULATED)."""
    ids = CountingIdGenerator()
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

    class Wired:
        pass

    wired = Wired()
    wired.store = store
    wired.clock = clock
    wired.ids = ids
    wired.medications = medications
    wired.regimens = regimens
    wired.sources = sources
    wired.source_fields = source_fields
    wired.dose_rules = dose_rules
    wired.occurrences = occurrences
    wired.events = events
    wired.sessions = sessions
    wired.challenges = challenges
    wired.traces = traces
    wired.enrollment = enrollment
    wired.schedule = schedule
    wired.self_report = self_report
    return wired
