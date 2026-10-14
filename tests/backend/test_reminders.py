"""VERIFIED LOCAL with InMemory persistence; medication changes remain forbidden."""

from uuid import uuid4

import pytest
from app.application.reminders import ReminderService
from app.domain.errors import NotFoundError, ValidationError
from app.infrastructure.memory_repos import (
    InMemoryDoseOccurrenceRepository,
    InMemoryRegimenVersionRepository,
    InMemoryStore,
    SystemClock,
)
from app.infrastructure.reminder_repos import MemoryReminderRepository


def test_reminder_validates_scope_and_closed_occurrence_without_writes():
    store = InMemoryStore()
    occurrences = InMemoryDoseOccurrenceRepository(store)
    regimens = InMemoryRegimenVersionRepository(store)
    service = ReminderService(
        repository=MemoryReminderRepository(store), occurrences=occurrences, regimens=regimens, clock=SystemClock()
    )
    patient, occurrence = uuid4(), uuid4()
    with pytest.raises(NotFoundError):
        service.snooze(patient_id=patient, occurrence_id=occurrence, minutes=15)
    with pytest.raises(ValidationError):
        service.snooze(patient_id=patient, occurrence_id=occurrence, minutes=-1)
    assert not store.reminders and not store.events and not store.regimens


@pytest.mark.parametrize(
    "state,status", [("active", "closed"), ("ended", "scheduled"), ("pending_clarification", "scheduled")]
)
def test_closed_or_nonactive_occurrence_refuses_reminder(state, status):
    from datetime import UTC, datetime

    from app.contracts.dto import DoseOccurrenceDTO, RegimenVersionDTO

    store = InMemoryStore()
    patient, regimen, occurrence = uuid4(), uuid4(), uuid4()
    row = RegimenVersionDTO(
        id=regimen,
        patient_id=patient,
        patient_medication_id=uuid4(),
        source_id=None,
        version_no=1,
        state=state,
        dose_amount=1,
        dose_unit="tablet",
        frequency_rule=None,
        is_prn=False,
        route=None,
        food_instruction=None,
        effective_from=None,
        effective_to=None,
        supersedes_id=None,
        confirmation_challenge_id=None,
        created_at=datetime.now(UTC),
    )
    regimens = InMemoryRegimenVersionRepository(store)
    regimens.add(row)
    occurrences = InMemoryDoseOccurrenceRepository(store)
    occurrences.add(
        DoseOccurrenceDTO(
            id=occurrence,
            patient_id=patient,
            regimen_id=regimen,
            rule_id=uuid4(),
            due_at=datetime.now(UTC),
            status=status,
            generation_key="DEMO-reminder",
        )
    )
    service = ReminderService(
        repository=MemoryReminderRepository(store), occurrences=occurrences, regimens=regimens, clock=SystemClock()
    )
    with pytest.raises(ValidationError):
        service.snooze(patient_id=patient, occurrence_id=occurrence, minutes=15)
    assert not store.reminders and not store.events
    assert regimens.get(patient, regimen) == row
