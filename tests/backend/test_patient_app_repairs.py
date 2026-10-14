"""SIMULATED schedule alerts/feedback. No model, audio or email provider calls."""

from datetime import timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from app.application.patient_feedback import FeedbackService
from app.application.reminder_alerts import ReminderAlertService
from app.application.reminders import ReminderService
from app.contracts.dto import FrequencyRuleDTO, RegimenDraftInput
from app.contracts.patient_feedback import FeedbackInput
from app.domain.errors import ValidationError
from app.infrastructure.feedback_repos import MemoryFeedback
from app.infrastructure.reminder_repos import MemoryReminderRepository
from pydantic import ValidationError as SchemaError

PATIENT = UUID(int=100)


def activate(wired, minutes, name="DEMO Metformin"):
    time = (wired.clock.now() + timedelta(minutes=minutes)).astimezone(ZoneInfo("Asia/Singapore")).strftime("%H:%M")
    draft = wired.enrollment.enroll_draft(
        patient_id=PATIENT,
        draft=RegimenDraftInput(
            medication_name=name,
            dose_amount=500,
            dose_unit="mg",
            food_instruction="after food",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=[time]),
        ),
    )
    wired.enrollment.review_source_fields(patient_id=PATIENT, source_id=draft.regimen.source_id)
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT, regimen_id=draft.regimen.id, session_id=uuid4(), session_state_version=1
    )
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=challenge.id)
    wired.enrollment.activate_regimen(
        patient_id=PATIENT,
        regimen_id=draft.regimen.id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )
    return draft.regimen.id


def services(wired):
    reminder = ReminderService(
        repository=MemoryReminderRepository(wired.store),
        occurrences=wired.occurrences,
        regimens=wired.regimens,
        clock=wired.clock,
    )
    alerts = ReminderAlertService(
        enrollment=wired.enrollment,
        schedule=wired.schedule,
        occurrences=wired.occurrences,
        events=wired.events,
        reminders=reminder,
        clock=wired.clock,
    )
    return reminder, alerts


def test_server_time_lead_snooze_and_alerts_do_not_write_intake_or_regimen(wired):
    regimen = activate(wired, 10)
    reminder, alerts = services(wired)
    assert not alerts.current(PATIENT, lead_minutes=0, timezone="Asia/Singapore")
    early = alerts.current(PATIENT, lead_minutes=15, timezone="Asia/Singapore")
    assert len(early) == 1 and early[0].dose_amount == 500 and early[0].food_instruction == "after food"
    wired.clock.advance(minutes=10)
    due = alerts.current(PATIENT, lead_minutes=0, timezone="Asia/Singapore")
    assert len(due) == 1
    before = wired.regimens.get(PATIENT, regimen)
    reminder.snooze(patient_id=PATIENT, occurrence_id=due[0].occurrence_id, minutes=15)
    assert not alerts.current(PATIENT, lead_minutes=0, timezone="Asia/Singapore")
    wired.clock.advance(minutes=15)
    repeated = alerts.current(PATIENT, lead_minutes=0, timezone="Asia/Singapore")
    assert len(repeated) == 1 and repeated[0].key != due[0].key
    assert not wired.store.events and wired.regimens.get(PATIENT, regimen) == before
    assert not alerts.current(UUID(int=200), lead_minutes=120, timezone="Asia/Singapore")


def test_alerts_check_all_medications_not_only_selected_one(wired):
    activate(wired, 10)
    activate(wired, 20, "DEMO second medication")
    _, alerts = services(wired)
    wired.clock.advance(minutes=25)
    assert len(alerts.current(PATIENT, lead_minutes=0, timezone="Asia/Singapore")) == 2


def test_feedback_owned_idempotent_and_no_patient_identity_in_input(wired):
    rows = {}
    service = FeedbackService(MemoryFeedback(rows), wired.clock)
    payload = FeedbackInput(id=uuid4(), category="issue", message="DEMO app display issue")
    first = service.submit(PATIENT, payload)
    assert service.submit(PATIENT, payload) == first and len(rows) == 1
    other = service.submit(UUID(int=200), payload)
    assert other.patient_id != first.patient_id and len(rows) == 2
    with pytest.raises(ValidationError):
        service.submit(PATIENT, payload.model_copy(update={"message": "Different DEMO issue"}))
    with pytest.raises(SchemaError):
        FeedbackInput(**payload.model_dump(), patient_id=PATIENT)
