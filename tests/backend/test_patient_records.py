"""VERIFIED LOCAL policy tests; persistence here is explicitly in-memory."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from app.application.observations import ObservationService
from app.contracts.observations import ObservationInput
from app.domain.errors import NotFoundError, ValidationError
from app.infrastructure.memory_repos import InMemoryPatientMedicationRepository
from app.infrastructure.observation_repos import MemoryObservations
from app.transport.app_factory import create_app
from app.transport.container import build_container
from fastapi.testclient import TestClient


def test_observation_requires_confirmation_is_idempotent_owned_and_read_only(wired):
    repository = MemoryObservations()
    service = ObservationService(repository, wired.medications, wired.clock)
    patient, other = uuid4(), uuid4()
    values = ObservationInput(id=uuid4(), occurred_at=wired.clock.now(), description="DEMO felt dizzy")
    with pytest.raises(ValidationError):
        service.save(patient, values)
    assert service.list(patient, wired.clock.now() - timedelta(days=1), wired.clock.now() + timedelta(days=1)) == []
    confirmed = values.model_copy(update={"confirmed": True})
    first = service.save(patient, confirmed)
    assert service.save(patient, confirmed).id == first.id
    assert service.list(other, wired.clock.now() - timedelta(days=1), wired.clock.now() + timedelta(days=1)) == []
    with pytest.raises(NotFoundError):
        service.delete(other, first.id)
    service.save(patient, confirmed.model_copy(update={"description": "DEMO feeling better"}))
    assert repository.get(patient, first.id).description == "DEMO feeling better"
    assert not wired.store.events and not wired.store.regimens
    service.delete(patient, first.id)
    assert repository.get(patient, first.id) is None


def test_observation_rejects_foreign_medication_and_future_time(wired):
    service = ObservationService(MemoryObservations(), wired.medications, wired.clock)
    values = ObservationInput(id=uuid4(), occurred_at=wired.clock.now(), description="DEMO well", confirmed=True)
    with pytest.raises(NotFoundError):
        service.save(uuid4(), values.model_copy(update={"medication_id": uuid4()}))
    with pytest.raises(ValidationError):
        service.save(uuid4(), values.model_copy(update={"occurred_at": wired.clock.now() + timedelta(hours=1)}))


def test_summary_calendar_window_and_no_data_are_honest(clock):
    container = build_container(clock=clock)
    patient = uuid4()
    month = container.review_summary.generate(patient, "month")
    assert month.window_start == datetime(2026, 9, 30, 16, tzinfo=UTC)
    assert month.window_end == clock.now()
    week = container.review_summary.generate(patient, "week")
    assert week.window_start == datetime(2026, 10, 11, 16, tzinfo=UTC)
    assert month.medications == [] and month.observations == [] and month.reported_taken == 0
    assert "not a missed dose" in month.coverage_note and "not absence of symptoms" in month.coverage_note
    assert not container.store.occurrences and not container.store.events
    with pytest.raises(ValidationError):
        container.review_summary.generate(patient, "course")
    with pytest.raises(NotFoundError):
        container.review_summary.generate(patient, "course", uuid4())


def test_http_owner_body_rejected_and_profile_persists(clock):
    client = TestClient(create_app(build_container(clock=clock)))
    owner = {"client_id": "DEMO-record-owner"}
    assert client.post("/api/demo/start", json=owner).status_code == 200
    body = {"id": str(uuid4()), "occurred_at": clock.now().isoformat(), "description": "DEMO well", "confirmed": True}
    assert (
        client.put("/api/me/health-observations", params=owner, json={**body, "patient_id": str(uuid4())}).status_code
        == 422
    )
    saved = client.put("/api/me/health-observations", params=owner, json=body)
    assert saved.status_code == 200
    assert client.get("/api/me/health-observations", params={"client_id": "DEMO-other"}).json() == []
    assert client.put("/api/me/preferences", params=owner, json={"display_name": "DEMO Alice"}).status_code == 200
    assert client.get("/api/me/preferences", params=owner).json()["display_name"] == "DEMO Alice"
    assert client.get("/api/me/preferences", params={"client_id": "DEMO-other"}).json()["display_name"] is None


def test_prepare_review_preserves_patient_words_and_cannot_write(wired):
    service = ObservationService(MemoryObservations(), InMemoryPatientMedicationRepository(wired.store), wired.clock)
    review = service.prepare_review("DEMO felt nauseous after my medicine")
    assert review.description == "DEMO felt nauseous after my medicine"
    assert review.requires_patient_review is True
    assert review.urgent_help_advised is False
    assert service.prepare_review("DEMO I cannot breathe").urgent_help_advised is True
    assert not wired.store.events and not wired.store.regimens
    with pytest.raises(ValidationError):
        service.prepare_review("x" * 1001)


def test_materialization_returns_the_stored_winner_id_after_a_generation_race(wired):
    from app.application.dosing import DoseScheduleService
    from app.contracts.dto import FrequencyRuleDTO, RegimenDraftInput

    patient = uuid4()
    draft = wired.enrollment.enroll_draft(
        patient_id=patient,
        draft=RegimenDraftInput(
            medication_name="DEMO race",
            dose_amount=1,
            dose_unit="tablet",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00"]),
            food_instruction="after food",
        ),
    )
    wired.enrollment.review_source_fields(patient_id=patient, source_id=draft.medication.source_id, field_ids=None)
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=patient, regimen_id=draft.regimen.id, session_id=uuid4(), session_state_version=1
    )
    wired.enrollment.confirm_challenge(patient_id=patient, challenge_id=challenge.id)
    wired.enrollment.activate_regimen(
        patient_id=patient,
        regimen_id=draft.regimen.id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )
    winner = uuid4()

    class RacingRepository:
        def list_for_regimen(self, owner, regimen, start, end):
            return wired.occurrences.list_for_regimen(owner, regimen, start, end)

        def find_by_generation_key(self, owner, key):
            return wired.occurrences.find_by_generation_key(owner, key)

        def add(self, row):
            # A competing request wins with a different database ID.
            wired.occurrences.add(row.model_copy(update={"id": winner}))

    schedule = DoseScheduleService(
        regimens=wired.regimens,
        rules=wired.dose_rules,
        occurrences=RacingRepository(),
        clock=wired.clock,
        ids=wired.ids,
    )
    rows = schedule.materialize(patient_id=patient, regimen_id=draft.regimen.id, days=1)
    assert len(rows) == 1 and rows[0].id == winner
    assert len(wired.store.occurrences) == 1 and not wired.store.events


def test_summary_counts_stored_scheduled_prn_and_feelings_without_regenerating_history(wired):
    """SIMULATED stored read-model fixtures, not a production intake shortcut."""
    from app.application.review_summary import ReviewSummaryService
    from app.contracts.dto import DoseEventDTO, DoseOccurrenceDTO, FrequencyRuleDTO, RegimenDraftInput
    from app.contracts.enums import IntakeStatus, OccurrenceStatus, RegimenState

    wired.clock.advance(hours=2)  # Singapore09:00
    patient = uuid4()
    today = wired.clock.now().astimezone(ZoneInfo("Asia/Singapore")).date()

    def plan(name, prn=False, start=None):
        draft = wired.enrollment.enroll_draft(
            patient_id=patient,
            draft=RegimenDraftInput(
                medication_name=name,
                dose_amount=1,
                dose_unit="tablet",
                is_prn=prn,
                frequency_rule=None if prn else FrequencyRuleDTO(kind="daily", local_times=["08:00", "08:30"]),
                food_instruction="as needed" if prn else "after food",
                course_start_date=start,
            ),
        )
        regimen = draft.regimen.model_copy(
            update={"state": RegimenState.ACTIVE, "effective_from": wired.clock.now() - timedelta(hours=2)}
        )
        wired.regimens.update(regimen)
        return draft.medication, regimen

    medication, scheduled = plan("DEMO scheduled", start=today)
    _, prn = plan("DEMO as needed", True)
    plan("DEMO future course", start=today + timedelta(days=1))
    occurrences = []
    for minutes in [60, 30]:
        row = DoseOccurrenceDTO(
            id=uuid4(),
            patient_id=patient,
            regimen_id=scheduled.id,
            rule_id=uuid4(),
            due_at=wired.clock.now() - timedelta(minutes=minutes),
            status=OccurrenceStatus.SCHEDULED,
            generation_key=f"DEMO-summary-{minutes}",
        )
        wired.occurrences.add(row)
        occurrences.append(row)
    for regimen, occurrence, status in [
        (scheduled, occurrences[0].id, IntakeStatus.REPORTED_TAKEN),
        (prn, None, IntakeStatus.UNSURE),
    ]:
        wired.events.add(
            DoseEventDTO(
                id=uuid4(),
                patient_id=patient,
                regimen_id=regimen.id,
                occurrence_id=occurrence,
                event_time=wired.clock.now() - timedelta(minutes=5),
                intake_status=status,
                idempotency_key="DEMO-summary-" + uuid4().hex,
                created_at=wired.clock.now(),
            )
        )
    observations = ObservationService(MemoryObservations(), wired.medications, wired.clock)
    observations.save(
        patient,
        ObservationInput(
            id=uuid4(),
            occurred_at=wired.clock.now() - timedelta(minutes=1),
            description="DEMO felt unwell",
            medication_id=medication.id,
            confirmed=True,
        ),
    )
    service = ReviewSummaryService(wired.enrollment, wired.occurrences, wired.events, observations, wired.clock)
    before = (dict(wired.store.events), dict(wired.store.occurrences), dict(wired.store.regimens))
    summary = service.generate(patient, "week")
    assert summary.reported_taken == 1 and summary.unsure == 1 and summary.reported_not_taken == 0
    assert {row.name for row in summary.medications} == {"DEMO scheduled", "DEMO as needed"}
    assert sum(row.without_report for row in summary.medications) == 1
    assert sum(row.recorded_occurrences for row in summary.medications) == 2
    assert summary.observations[0].description == "DEMO felt unwell"
    course = service.generate(patient, "course", scheduled.id)
    assert len(course.medications) == 1 and course.unsure == 0 and course.reported_taken == 1
    assert before == (wired.store.events, wired.store.occurrences, wired.store.regimens)
