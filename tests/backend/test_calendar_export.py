"""Synthetic contract checks for calendar-event titles and RFC5545 text."""

from datetime import UTC, datetime
from uuid import UUID

from app.application.calendar_export import calendar_export
from app.application.reminder_plan import PlannedReminder


def test_export_uses_the_planned_medicine_name_and_valid_utf8_folding():
    row = PlannedReminder(
        occurrence_id=UUID(int=1),
        regimen_id=UUID(int=2),
        rule_id=UUID(int=3),
        medication_name="DEMO 阿莫; A, B\\C",
        due_at=datetime(2026, 10, 16, 12, 0, tzinfo=UTC),
        remind_at=datetime(2026, 10, 16, 11, 45, tzinfo=UTC),
    )

    result = calendar_export([row], now=datetime(2026, 10, 16, 10, 0, tzinfo=UTC), lead_minutes=15)
    physical_lines = result.split("\r\n")[:-1]

    assert any(line.startswith("SUMMARY:Medication reminder:") for line in physical_lines)
    assert "\\;" in result and "\\," in result and "\\\\" in result
    assert all(len(line.encode("utf-8")) <= 75 for line in physical_lines)

    unfolded = []
    for line in physical_lines:
        if line.startswith(" "):
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    summary = next(line for line in unfolded if line.startswith("SUMMARY:"))
    assert summary == r"SUMMARY:Medication reminder: DEMO 阿莫\; A\, B\\C"
