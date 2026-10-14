"""Reviewed course dates are independent of version timestamps (SIMULATED)."""

from datetime import timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from app.contracts.dto import FrequencyRuleDTO, RegimenDraftInput
from app.contracts.enums import IntakeStatus
from app.domain.errors import ValidationError
from pydantic import ValidationError as SchemaError

PATIENT = UUID(int=100)


def activate(wired, *, start, end, prn=False, weekly=False):
    draft = RegimenDraftInput(
        medication_name="DEMO Metformin",
        dose_amount=500,
        dose_unit="mg",
        course_start_date=start,
        course_end_date=end,
        is_prn=prn,
        frequency_rule=None
        if prn
        else FrequencyRuleDTO(
            kind="weekly" if weekly else "daily",
            local_times=["20:00"],
            days_of_week=[start.isoweekday()] if weekly else [],
        ),
        food_instruction="as needed" if prn else None,
    )
    enrolled = wired.enrollment.enroll_draft(patient_id=PATIENT, draft=draft)
    wired.enrollment.review_source_fields(patient_id=PATIENT, source_id=enrolled.regimen.source_id)
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT,
        regimen_id=enrolled.regimen.id,
        session_id=UUID(int=400),
        session_state_version=1,
    )
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=challenge.id)
    result = wired.enrollment.activate_regimen(
        patient_id=PATIENT,
        regimen_id=enrolled.regimen.id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )
    return result.regimen


def test_course_dates_reviewed_and_inclusive_window(wired):
    today = wired.clock.now().astimezone(ZoneInfo("Asia/Singapore")).date()
    regimen = activate(wired, start=today + timedelta(days=1), end=today + timedelta(days=2))
    assert regimen.effective_from.date() != regimen.course_start_date
    fields = wired.source_fields.list_for_source(PATIENT, regimen.source_id)
    assert {field.field_name.value for field in fields} >= {"course_start_date", "course_end_date"}
    occurrences = wired.schedule.materialize(patient_id=PATIENT, regimen_id=regimen.id, days=6)
    assert [row.due_at.astimezone(ZoneInfo("Asia/Singapore")).date() for row in occurrences] == [
        regimen.course_start_date,
        regimen.course_end_date,
    ]
    wired.clock.advance(days=4)
    assert wired.schedule.find_due(patient_id=PATIENT, regimen_id=regimen.id).occurrence is None
    assert wired.regimens.get(PATIENT, regimen.id).course_end_date == today + timedelta(days=2)


def test_weekly_course_does_not_become_daily(wired):
    today = wired.clock.now().astimezone(ZoneInfo("Asia/Singapore")).date()
    regimen = activate(wired, start=today, end=today + timedelta(days=8), weekly=True)
    rows = wired.schedule.materialize(patient_id=PATIENT, regimen_id=regimen.id, days=10)
    assert len(rows) == 2 and all(
        row.due_at.astimezone(ZoneInfo("Asia/Singapore")).date().isoweekday() == today.isoweekday() for row in rows
    )


def test_prn_course_expired_cannot_prepare_report(wired):
    today = wired.clock.now().astimezone(ZoneInfo("Asia/Singapore")).date()
    regimen = activate(wired, start=today - timedelta(days=2), end=today - timedelta(days=1), prn=True)
    with pytest.raises(ValidationError, match="outside"):
        wired.self_report.request_confirmation(
            patient_id=PATIENT,
            regimen_id=regimen.id,
            occurrence_id=None,
            intake_status=IntakeStatus.REPORTED_TAKEN,
            idempotency_key="DEMO-expired",
            session_id=UUID(int=500),
            session_state_version=1,
        )
    assert not wired.store.events


@pytest.mark.parametrize("start,end", [(None, "2026-10-14"), ("2026-10-15", "2026-10-14")])
def test_invalid_course_dates_rejected(start, end):
    with pytest.raises(SchemaError):
        RegimenDraftInput(medication_name="DEMO", course_start_date=start, course_end_date=end)
