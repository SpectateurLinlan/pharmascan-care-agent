"""Focused SIMULATED coverage for bounded, read-only calendar range exports."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from app.application.calendar_export import calendar_export
from app.application.dosing import DoseScheduleService
from app.application.reminder_plan import PlannedReminder, ReminderPlanService
from app.contracts.enums import OccurrenceStatus, RegimenState
from app.contracts.long_term import CareTask
from app.domain.errors import ValidationError
from app.transport.routes.reminders import calendar as calendar_route
from icalendar import Calendar

from .test_patient_app_repairs import PATIENT, activate, services


class RegimenReadView:
    def __init__(self, repository, overrides):
        self.repository = repository
        self.overrides = overrides

    def get(self, patient_id, regimen_id):
        regimen = self.repository.get(patient_id, regimen_id)
        if regimen and regimen_id in self.overrides:
            return regimen.model_copy(update=self.overrides[regimen_id])
        return regimen

    def list_for_medication(self, patient_id, medication_id):
        return [self.get(patient_id, row.id) for row in self.repository.list_for_medication(patient_id, medication_id)]


def calendar_plan(wired, overrides=None):
    reminders, _ = services(wired)
    regimens = RegimenReadView(wired.regimens, overrides or {})
    schedule = DoseScheduleService(
        regimens=regimens,
        rules=wired.dose_rules,
        occurrences=wired.occurrences,
        clock=wired.clock,
        ids=wired.ids,
    )
    return ReminderPlanService(
        medications=wired.medications,
        regimens=regimens,
        schedule=schedule,
        events=wired.events,
        reminders=reminders,
        clock=wired.clock,
    )


def test_full_remaining_course_uses_inclusive_end_date_and_does_not_materialize(wired):
    regimen_id = activate(wired, 60)
    plan = calendar_plan(
        wired,
        {regimen_id: {"course_start_date": date(2026, 10, 13), "course_end_date": date(2026, 10, 15)}},
    )
    before = dict(wired.store.occurrences)

    rows, end_date = plan.calendar_export_rows(
        PATIENT,
        lead_minutes=15,
        start_date=date(2026, 10, 13),
        end_date=None,
        full_remaining_course=True,
    )

    assert end_date == date(2026, 10, 15)
    assert [row.due_at.astimezone(ZoneInfo("Asia/Singapore")).date() for row in rows] == [
        date(2026, 10, 13),
        date(2026, 10, 14),
        date(2026, 10, 15),
    ]
    assert wired.store.occurrences == before
    assert all(row.occurrence_id.int != 0 for row in rows)


def test_open_ended_course_uses_a_finite_90_day_horizon(wired):
    activate(wired, 60)
    rows, end_date = calendar_plan(wired).calendar_export_rows(
        PATIENT,
        lead_minutes=0,
        start_date=date(2026, 10, 13),
        end_date=None,
        full_remaining_course=True,
    )

    assert end_date == date(2027, 1, 10)
    assert len(rows) == 90


def test_expired_ended_and_superseded_courses_do_not_export_future_events(wired):
    overrides = {}
    for index, update in enumerate(
        [
            {"course_end_date": date(2026, 10, 12)},
            {"state": RegimenState.ENDED, "course_end_date": date(2026, 10, 20)},
            {"state": RegimenState.SUPERSEDED, "course_end_date": date(2026, 10, 20)},
        ]
    ):
        regimen_id = activate(wired, 60 + index, name=f"DEMO calendar course {index}")
        overrides[regimen_id] = update

    plan = calendar_plan(wired, overrides)

    rows, _ = plan.calendar_export_rows(
        PATIENT,
        lead_minutes=0,
        start_date=date(2026, 10, 13),
        end_date=date(2026, 10, 20),
    )
    assert rows == []


def test_export_uses_only_the_current_version_of_a_supersession_chain(wired):
    old_id = activate(wired, 60, name="DEMO chain previous version")
    current_id = activate(wired, 120, name="DEMO chain current version")
    current_regimen = wired.regimens.get(PATIENT, current_id)
    medication_id = current_regimen.patient_medication_id
    chain_overrides = {
        old_id: {"state": RegimenState.SUPERSEDED, "patient_medication_id": medication_id},
        current_id: {"supersedes_id": old_id},
    }

    class ChainRegimenReadView(RegimenReadView):
        def list_for_medication(self, patient_id, medication_id):
            if medication_id == medication_id_for_chain:
                return [self.get(patient_id, old_id), self.get(patient_id, current_id)]
            return []

    medication_id_for_chain = medication_id
    regimens = ChainRegimenReadView(wired.regimens, chain_overrides)

    class ChainMedicationReadView:
        def list_for_patient(self, patient_id):
            return [wired.medications.get(patient_id, medication_id_for_chain)]

    reminders, _ = services(wired)
    schedule = DoseScheduleService(
        regimens=regimens,
        rules=wired.dose_rules,
        occurrences=wired.occurrences,
        clock=wired.clock,
        ids=wired.ids,
    )
    plan = ReminderPlanService(
        medications=ChainMedicationReadView(),
        regimens=regimens,
        schedule=schedule,
        events=wired.events,
        reminders=reminders,
        clock=wired.clock,
    )
    rows, _ = plan.calendar_export_rows(
        PATIENT,
        lead_minutes=0,
        start_date=date(2026, 10, 13),
        end_date=date(2026, 10, 13),
    )

    assert rows
    assert {row.regimen_id for row in rows} == {current_id}
    assert regimens.get(PATIENT, current_id).supersedes_id == old_id


def test_closed_existing_occurrence_is_honored_as_a_schedule_exception(wired):
    regimen_id = activate(wired, 60)
    occurrence = wired.schedule.materialize(patient_id=PATIENT, regimen_id=regimen_id, days=1)[0]
    wired.occurrences.update(occurrence.model_copy(update={"status": OccurrenceStatus.CLOSED}))

    rows, _ = calendar_plan(wired).calendar_export_rows(
        PATIENT,
        lead_minutes=0,
        start_date=date(2026, 10, 13),
        end_date=date(2026, 10, 13),
    )

    assert rows == []


def test_dst_expansion_uses_rule_timezone_and_returns_stable_projection_ids(wired):
    regimen_id = activate(wired, 60)
    rule = wired.dose_rules.list_for_regimen(PATIENT, regimen_id)[0]

    class NewYorkRuleView:
        def list_for_regimen(self, patient_id, selected_regimen):
            return [rule.model_copy(update={"local_times": ["08:00"], "timezone": "America/New_York"})]

    schedule = DoseScheduleService(
        regimens=wired.regimens,
        rules=NewYorkRuleView(),
        occurrences=wired.occurrences,
        clock=wired.clock,
        ids=wired.ids,
    )
    zone = ZoneInfo("America/New_York")
    start = datetime(2027, 3, 13, tzinfo=zone).astimezone(UTC)
    end = datetime(2027, 3, 16, tzinfo=zone).astimezone(UTC)

    first = schedule.calendar_occurrences(patient_id=PATIENT, regimen_id=regimen_id, start=start, end=end)
    second = schedule.calendar_occurrences(patient_id=PATIENT, regimen_id=regimen_id, start=start, end=end)

    assert [row.due_at for row in first] == [
        datetime(2027, 3, 13, 13, tzinfo=UTC),
        datetime(2027, 3, 14, 12, tzinfo=UTC),
        datetime(2027, 3, 15, 12, tzinfo=UTC),
    ]
    assert [row.id for row in first] == [row.id for row in second]


def test_ics_contains_one_task_event_with_deduplicated_future_offsets(wired):
    regimen_id = activate(wired, 60)
    plan = calendar_plan(wired)
    rows, _ = plan.calendar_export_rows(
        PATIENT,
        lead_minutes=15,
        start_date=date(2026, 10, 13),
        end_date=date(2026, 10, 14),
    )
    now = wired.clock.now()
    task = CareTask(
        patient_id=PATIENT,
        id=uuid4(),
        title="DEMO medication review",
        category="medication_review",
        due_at=now + timedelta(days=1),
        reminder_offsets=[60, 30, 60],
        created_at=now,
        updated_at=now,
    )

    text = calendar_export(rows, now=now, lead_minutes=15, tasks=[task])
    parsed = Calendar.from_ical(text)
    events = parsed.walk("VEVENT")
    task_events = [event for event in events if str(event["SUMMARY"]).startswith("Medication follow-up:")]

    assert len(events) == len(rows) + 1
    assert len(task_events) == 1
    assert len(task_events[0].walk("VALARM")) == 2
    assert len({str(event["UID"]) for event in events}) == len(events)
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert wired.regimens.get(PATIENT, regimen_id).state == RegimenState.ACTIVE


def test_calendar_api_defaults_to_30_days_and_accepts_90_day_range(wired):
    activate(wired, 60)
    plan = calendar_plan(wired)
    container = SimpleNamespace(
        reminder_plan=plan,
        preferences=SimpleNamespace(get=lambda _: SimpleNamespace(reminder_lead_minutes=15, timezone="Asia/Singapore")),
        clock=wired.clock,
        long_term=None,
    )
    principal = SimpleNamespace(patient_id=PATIENT)

    default_response = calendar_route(
        range_name=None,
        start_date=None,
        end_date=None,
        include_medications=True,
        include_tasks=True,
        days=None,
        principal=principal,
        container=container,
    )
    ninety_response = calendar_route(
        range_name="90",
        start_date=None,
        end_date=None,
        include_medications=True,
        include_tasks=False,
        days=None,
        principal=principal,
        container=container,
    )

    assert len(Calendar.from_ical(default_response.body).walk("VEVENT")) == 30
    assert len(Calendar.from_ical(ninety_response.body).walk("VEVENT")) == 90
    assert default_response.media_type == "text/calendar"


def test_custom_api_range_rejects_oversized_selection_and_empty_content(wired):
    container = SimpleNamespace(
        reminder_plan=calendar_plan(wired),
        preferences=SimpleNamespace(get=lambda _: SimpleNamespace(reminder_lead_minutes=0, timezone="Asia/Singapore")),
        clock=wired.clock,
        long_term=None,
    )
    principal = SimpleNamespace(patient_id=PATIENT)
    with pytest.raises(ValidationError, match="cannot exceed 366 days"):
        calendar_route(
            range_name="custom",
            start_date=date(2026, 10, 13),
            end_date=date(2027, 10, 14),
            include_medications=True,
            include_tasks=True,
            days=None,
            principal=principal,
            container=container,
        )
    with pytest.raises(ValidationError, match="Select medication reminders"):
        calendar_route(
            range_name="30",
            start_date=None,
            end_date=None,
            include_medications=False,
            include_tasks=False,
            days=None,
            principal=principal,
            container=container,
        )


def test_custom_api_range_includes_tasks_only_inside_selected_dates(wired):
    now = wired.clock.now()
    zone = ZoneInfo("Asia/Singapore")
    tasks = [
        CareTask(
            patient_id=PATIENT,
            id=uuid4(),
            title=f"DEMO date {day}",
            category="medication_review",
            due_at=datetime(2026, 10, day, 8, tzinfo=zone),
            reminder_minutes=30,
            created_at=now,
            updated_at=now,
        )
        for day in (14, 15, 17)
    ]

    class LongTermReadView:
        def actionable_tasks(self, patient_id, timezone):
            return tasks

    container = SimpleNamespace(
        reminder_plan=calendar_plan(wired),
        preferences=SimpleNamespace(get=lambda _: SimpleNamespace(reminder_lead_minutes=0, timezone="Asia/Singapore")),
        clock=wired.clock,
        long_term=LongTermReadView(),
    )
    response = calendar_route(
        range_name="custom",
        start_date=date(2026, 10, 15),
        end_date=date(2026, 10, 16),
        include_medications=False,
        include_tasks=True,
        days=None,
        principal=SimpleNamespace(patient_id=PATIENT),
        container=container,
    )

    events = Calendar.from_ical(response.body).walk("VEVENT")
    assert len(events) == 1
    assert "DEMO date 15" in str(events[0]["SUMMARY"])


def test_calendar_file_rejects_more_than_500_events_instead_of_truncating(wired):
    now = wired.clock.now()
    rows = [
        PlannedReminder(
            occurrence_id=uuid4(),
            regimen_id=uuid4(),
            rule_id=uuid4(),
            medication_name="DEMO medication",
            due_at=now + timedelta(minutes=index + 1),
            remind_at=now + timedelta(minutes=index + 1),
        )
        for index in range(501)
    ]
    with pytest.raises(ValidationError, match="exceeds 500 events"):
        calendar_export(rows, now=now, lead_minutes=0)
