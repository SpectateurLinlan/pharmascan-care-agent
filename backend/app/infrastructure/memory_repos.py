"""In-memory repositories implementing the Port protocols.

** SIMULATED ** — these are NOT a database. They exist so that the
application/agent layers can be exercised with real logic, real policy and
real boundaries while the PostgreSQL/Supabase environment is unavailable
(B02). They deliberately reproduce the SQL constraints of
supabase/migrations/202610130001_core.sql, including patient ownership
isolation: every lookup is scoped by patient_id, so a cross-patient read
returns None exactly as RLS would.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..contracts.dto import (
    AgentSessionDTO,
    ConfirmationChallengeDTO,
    DoseEventDTO,
    DoseOccurrenceDTO,
    DoseRuleDTO,
    PatientMedicationDTO,
    RegimenVersionDTO,
    SourceDocumentDTO,
    SourceFieldDTO,
    ToolTraceDTO,
)
from ..contracts.reminders import ReminderDTO


class SystemClock:
    """Default production clock (UTC, timezone-aware)."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class SequentialIdGenerator:
    """Deterministic UUID source: uuid4 + monotonic counter seed is avoided so
    tests can inject a fully predictable generator instead."""

    def new_id(self) -> UUID:
        return uuid4()


class InMemoryStore:
    """Single owner of all in-memory rows; injected into every repository."""

    def __init__(self) -> None:
        self.reminders: dict[tuple[UUID, UUID], ReminderDTO] = {}
        self.sources: dict[tuple[UUID, UUID], SourceDocumentDTO] = {}
        self.source_fields: dict[tuple[UUID, UUID], SourceFieldDTO] = {}
        self.medications: dict[tuple[UUID, UUID], PatientMedicationDTO] = {}
        self.regimens: dict[tuple[UUID, UUID], RegimenVersionDTO] = {}
        self.dose_rules: dict[tuple[UUID, UUID], DoseRuleDTO] = {}
        self.occurrences: dict[tuple[UUID, UUID], DoseOccurrenceDTO] = {}
        self.events: dict[tuple[UUID, UUID], DoseEventDTO] = {}
        self.sessions: dict[tuple[UUID, UUID], AgentSessionDTO] = {}
        self.challenges: dict[tuple[UUID, UUID], ConfirmationChallengeDTO] = {}
        self.traces: dict[tuple[UUID, UUID], ToolTraceDTO] = {}


class InMemorySourceDocumentRepository:
    """** SIMULATED ** in-memory repository."""

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    def get(self, patient_id: UUID, source_id: UUID) -> SourceDocumentDTO | None:
        return self._store.sources.get((patient_id, source_id))

    def add(self, document: SourceDocumentDTO) -> None:
        self._store.sources[(document.patient_id, document.id)] = document

    def update(self, document: SourceDocumentDTO) -> None:
        self._store.sources[(document.patient_id, document.id)] = document


class InMemorySourceFieldRepository:
    """** SIMULATED ** in-memory repository."""

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    def list_for_source(self, patient_id: UUID, source_id: UUID) -> list[SourceFieldDTO]:
        return [
            f for (owner, _), f in self._store.source_fields.items() if owner == patient_id and f.source_id == source_id
        ]

    def add(self, field: SourceFieldDTO) -> None:
        self._store.source_fields[(field.patient_id, field.id)] = field

    def update(self, field: SourceFieldDTO) -> None:
        self._store.source_fields[(field.patient_id, field.id)] = field


class InMemoryPatientMedicationRepository:
    """** SIMULATED ** in-memory repository."""

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    def get(self, patient_id: UUID, medication_id: UUID) -> PatientMedicationDTO | None:
        return self._store.medications.get((patient_id, medication_id))

    def list_for_patient(self, patient_id: UUID) -> list[PatientMedicationDTO]:
        return [m for (owner, _), m in self._store.medications.items() if owner == patient_id]

    def add(self, medication: PatientMedicationDTO) -> None:
        self._store.medications[(medication.patient_id, medication.id)] = medication

    def update(self, medication: PatientMedicationDTO) -> None:
        self._store.medications[(medication.patient_id, medication.id)] = medication


class InMemoryRegimenVersionRepository:
    """** SIMULATED ** in-memory repository.

    Enforces the one-active-regimen-per-medication uniqueness and the
    historical-immutability rule that the SQL triggers enforce.
    """

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    def get(self, patient_id: UUID, regimen_id: UUID) -> RegimenVersionDTO | None:
        return self._store.regimens.get((patient_id, regimen_id))

    def list_for_medication(self, patient_id: UUID, medication_id: UUID) -> list[RegimenVersionDTO]:
        rows = [
            r
            for (owner, _), r in self._store.regimens.items()
            if owner == patient_id and r.patient_medication_id == medication_id
        ]
        return sorted(rows, key=lambda r: r.version_no)

    def find_active_for_medication(self, patient_id: UUID, medication_id: UUID) -> RegimenVersionDTO | None:
        for regimen in self.list_for_medication(patient_id, medication_id):
            if regimen.state.value == "active":
                return regimen
        return None

    def next_version_no(self, patient_id: UUID, medication_id: UUID) -> int:
        existing = self.list_for_medication(patient_id, medication_id)
        return (existing[-1].version_no + 1) if existing else 1

    def add(self, regimen: RegimenVersionDTO) -> None:
        self._guard_immutable_history(regimen)
        if regimen.state.value == "active":
            current = self.find_active_for_medication(regimen.patient_id, regimen.patient_medication_id)
            if current is not None and current.id != regimen.id:
                raise ValueError("one active regimen per medication is enforced by a unique index")
        self._store.regimens[(regimen.patient_id, regimen.id)] = regimen

    def update(self, regimen: RegimenVersionDTO) -> None:
        key = (regimen.patient_id, regimen.id)
        previous = self._store.regimens.get(key)
        if previous is None:
            raise KeyError(f"regimen {regimen.id} not found")
        self._guard_immutable_history(regimen, previous=previous)
        self._store.regimens[key] = regimen

    @staticmethod
    def _guard_immutable_history(regimen: RegimenVersionDTO, previous: RegimenVersionDTO | None = None) -> None:
        """Mirror core_guard_regimen: ended/superseded rows are frozen."""
        if previous is None:
            return
        if previous.state.value in ("ended", "superseded"):
            raise ValueError("historical regimen versions are immutable")
        if previous.state.value == "active" and regimen.state.value not in (
            "ended",
            "superseded",
        ):
            changed = regimen.model_dump(exclude={"state", "effective_to"}) != previous.model_dump(
                exclude={"state", "effective_to"}
            )
            if changed:
                raise ValueError("an active regimen cannot be edited, only retired")


class InMemoryDoseRuleRepository:
    """** SIMULATED ** in-memory repository."""

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    def list_for_regimen(self, patient_id: UUID, regimen_id: UUID) -> list[DoseRuleDTO]:
        return [
            r for (owner, _), r in self._store.dose_rules.items() if owner == patient_id and r.regimen_id == regimen_id
        ]

    def add(self, rule: DoseRuleDTO) -> None:
        self._store.dose_rules[(rule.patient_id, rule.id)] = rule


class InMemoryDoseOccurrenceRepository:
    """** SIMULATED ** in-memory repository with generation_key uniqueness."""

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    def get(self, patient_id: UUID, occurrence_id: UUID) -> DoseOccurrenceDTO | None:
        return self._store.occurrences.get((patient_id, occurrence_id))

    def find_by_generation_key(self, patient_id: UUID, key: str) -> DoseOccurrenceDTO | None:
        for (owner, _), occurrence in self._store.occurrences.items():
            if owner == patient_id and occurrence.generation_key == key:
                return occurrence
        return None

    def list_for_regimen(
        self, patient_id: UUID, regimen_id: UUID, window_start: datetime, window_end: datetime
    ) -> list[DoseOccurrenceDTO]:
        rows = [
            o
            for (owner, _), o in self._store.occurrences.items()
            if owner == patient_id and o.regimen_id == regimen_id and window_start <= o.due_at < window_end
        ]
        return sorted(rows, key=lambda o: o.due_at)

    def add(self, occurrence: DoseOccurrenceDTO) -> None:
        existing = self.find_by_generation_key(occurrence.patient_id, occurrence.generation_key)
        if existing is not None and existing.id != occurrence.id:
            raise ValueError("duplicate generation_key would violate the unique index")
        self._store.occurrences[(occurrence.patient_id, occurrence.id)] = occurrence

    def update(self, occurrence: DoseOccurrenceDTO) -> None:
        self._store.occurrences[(occurrence.patient_id, occurrence.id)] = occurrence


class InMemoryDoseEventRepository:
    """** SIMULATED ** in-memory repository.

    Enforces both unique keys from the migration:
    (patient_id, occurrence_id) and (patient_id, idempotency_key). It also
    refuses any event that claims ingestion was proven.
    """

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    def find_by_idempotency_key(self, patient_id: UUID, key: str) -> DoseEventDTO | None:
        for (owner, _), event in self._store.events.items():
            if owner == patient_id and event.idempotency_key == key:
                return event
        return None

    def find_by_occurrence(self, patient_id: UUID, occurrence_id: UUID) -> DoseEventDTO | None:
        for (owner, _), event in self._store.events.items():
            if owner == patient_id and event.occurrence_id == occurrence_id:
                return event
        return None

    def list_for_patient(self, patient_id: UUID, window_start: datetime, window_end: datetime) -> list[DoseEventDTO]:
        rows = [
            e
            for (owner, _), e in self._store.events.items()
            if owner == patient_id and window_start <= e.event_time < window_end
        ]
        return sorted(rows, key=lambda e: e.event_time)

    def add(self, event: DoseEventDTO) -> None:
        if event.ingestion_proven:
            raise ValueError("ingestion_proven must never be true (CHECK constraint)")
        if event.visual_status.value != "not_checked":
            raise ValueError("P0 slice: photo evidence is unsupported, visual_status must be not_checked")
        if self.find_by_idempotency_key(event.patient_id, event.idempotency_key) is not None:
            raise ValueError("duplicate idempotency_key would violate the unique index")
        if event.occurrence_id is not None:
            if self.find_by_occurrence(event.patient_id, event.occurrence_id) is not None:
                raise ValueError("duplicate (patient_id, occurrence_id) would violate the unique index")
        self._store.events[(event.patient_id, event.id)] = event


class InMemoryAgentSessionRepository:
    """** SIMULATED ** in-memory repository."""

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    def get(self, patient_id: UUID, session_id: UUID) -> AgentSessionDTO | None:
        return self._store.sessions.get((patient_id, session_id))

    def add(self, session: AgentSessionDTO) -> None:
        self._store.sessions[(session.patient_id, session.id)] = session

    def update(self, session: AgentSessionDTO) -> None:
        self._store.sessions[(session.patient_id, session.id)] = session

    def clear_conversation_text(self, patient_id: UUID) -> None:
        """Privacy operation preserves clinical references and confirmation lifecycle."""
        for key, session in list(self._store.sessions.items()):
            if key[0] == patient_id:
                context = session.context.model_copy(update={"recent_turns": [], "conversation_summary": ""})
                self._store.sessions[key] = session.model_copy(update={"context": context})

    def is_owned_by_other_patient(self, patient_id: UUID, session_id: UUID) -> bool:
        """Ownership probe: a session id may never be shared across patients."""
        return any(owner != patient_id and sid == session_id for owner, sid in self._store.sessions)


class InMemoryConfirmationChallengeRepository:
    """** SIMULATED ** in-memory repository with token_hash uniqueness."""

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    def get(self, patient_id: UUID, challenge_id: UUID) -> ConfirmationChallengeDTO | None:
        return self._store.challenges.get((patient_id, challenge_id))

    def find_by_token_hash(self, patient_id: UUID, token_hash: str) -> ConfirmationChallengeDTO | None:
        for (owner, _), challenge in self._store.challenges.items():
            if owner == patient_id and challenge.token_hash == token_hash:
                return challenge
        return None

    def find_by_idempotency_key(self, patient_id: UUID, idempotency_key: str) -> ConfirmationChallengeDTO | None:
        """Patient-scoped lookup; mirrors UNIQUE (patient_id, idempotency_key)."""
        for (owner, _), challenge in self._store.challenges.items():
            if owner == patient_id and challenge.idempotency_key == idempotency_key:
                return challenge
        return None

    def add(self, challenge: ConfirmationChallengeDTO) -> None:
        if self.find_by_token_hash(challenge.patient_id, challenge.token_hash) is not None:
            raise ValueError("duplicate token_hash would violate the unique index")
        if self.find_by_idempotency_key(challenge.patient_id, challenge.idempotency_key) is not None:
            raise ValueError("duplicate idempotency_key would violate the unique index")
        self._store.challenges[(challenge.patient_id, challenge.id)] = challenge

    def update(self, challenge: ConfirmationChallengeDTO) -> None:
        self._store.challenges[(challenge.patient_id, challenge.id)] = challenge


class InMemoryToolTraceRepository:
    """** SIMULATED ** in-memory repository."""

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    def add(self, trace: ToolTraceDTO) -> None:
        self._store.traces[(trace.patient_id, trace.id)] = trace

    def list_for_session(self, patient_id: UUID, session_id: UUID) -> list[ToolTraceDTO]:
        rows = [t for (owner, _), t in self._store.traces.items() if owner == patient_id and t.session_id == session_id]
        return sorted(rows, key=lambda t: t.called_at)
