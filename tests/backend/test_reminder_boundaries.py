"""Synthetic clock/application regressions; never writes production or sends push."""

from datetime import timedelta
from uuid import uuid4

import pytest
from app.application.calendar_export import calendar_export
from app.contracts.long_term import CareTask
from app.domain.errors import ValidationError
from icalendar import Calendar

from .test_patient_app_repairs import PATIENT, activate, services


@pytest.mark.parametrize("minutes", [15, 30])
def test_snooze_persists_without_moving_original_deadline(wired, minutes):
    plan = activate(wired, 0)
    occurrence = wired.schedule.materialize(patient_id=PATIENT, regimen_id=plan, days=1)[0]
    reminders, alerts = services(wired)
    deadline = reminders.deadline(PATIENT, occurrence)
    first = alerts.current(PATIENT, lead_minutes=0, timezone="Asia/Singapore")
    assert first and first[0].expires_at == deadline
    snoozed = reminders.snooze(patient_id=PATIENT, occurrence_id=occurrence.id, minutes=minutes)
    assert alerts.current(PATIENT, lead_minutes=0, timezone="Asia/Singapore") == []
    wired.clock.advance(minutes=minutes)
    due = alerts.current(PATIENT, lead_minutes=0, timezone="Asia/Singapore")
    assert due[0].remind_at == snoozed.remind_at and due[0].expires_at == deadline
    wired.clock.advance(seconds=(deadline - wired.clock.now()).total_seconds())
    assert alerts.current(PATIENT, lead_minutes=0, timezone="Asia/Singapore") == []
    with pytest.raises(ValidationError, match="original reminder deadline"):
        reminders.snooze(patient_id=PATIENT, occurrence_id=occurrence.id, minutes=minutes)
    assert not wired.store.events


def test_snooze_cannot_cross_the_next_scheduled_dose(wired):
    plan_id = activate(wired, 0)
    now = wired.clock.now()
    from zoneinfo import ZoneInfo

    next_time = (now + timedelta(minutes=20)).astimezone(ZoneInfo("Asia/Singapore")).strftime("%H:%M")
    for key, rule in list(wired.store.dose_rules.items()):
        if rule.regimen_id == plan_id:
            wired.store.dose_rules[key] = rule.model_copy(update={"local_times": [*rule.local_times, next_time]})
    occurrence = wired.schedule.materialize(patient_id=PATIENT, regimen_id=plan_id, days=1)[0]
    reminders, _ = services(wired)
    with pytest.raises(ValidationError, match="original reminder deadline"):
        reminders.snooze(patient_id=PATIENT, occurrence_id=occurrence.id, minutes=30)


def test_care_calendar_multiple_alarms_private_stable_and_escaped(wired):
    now = wired.clock.now()
    task = CareTask(
        patient_id=PATIENT,
        id=uuid4(),
        title="DEMO review; A,B",
        category="medication_review",
        due_at=now + timedelta(days=2),
        reminder_offsets=[1440, 60, 0],
        created_at=now,
        updated_at=now,
    )
    text = calendar_export([], now=now, lead_minutes=0, tasks=[task])
    parsed = Calendar.from_ical(text)
    assert len(parsed.walk("VEVENT")) == 1
    assert [alarm.decoded("TRIGGER") for alarm in parsed.walk("VALARM")] == [
        timedelta(days=-1),
        timedelta(hours=-1),
        timedelta(0),
    ]
    assert str(parsed.walk("VEVENT")[0]["SUMMARY"]) == "Medication follow-up: DEMO review; A,B"
    assert parsed.walk("VEVENT")[0]["CLASS"] == "PRIVATE"
    assert calendar_export([], now=now, lead_minutes=0, tasks=[task]) == text
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))
