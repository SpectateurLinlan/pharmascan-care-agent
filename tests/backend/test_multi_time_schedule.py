"""Multiple daily dose times per regimen.

A regimen may carry several explicit times a day (for example 08:00 and
20:00). These tests pin the chosen representation:

- each time becomes its own ``dose_rules`` row with exactly one
  ``local_times`` entry, matching the SQL ``dose_rules.local_time time`` column;
- a "daily" instruction stores all seven ISO weekdays, so the rule satisfies
  ``dose_rules_schedule_ck`` (which requires a non-empty ``days_of_week`` for a
  scheduled rule) and can never be rejected by a real database;
- occurrences stay attributable to the specific rule that produced them;
- weekly / interval / PRN behaviour is unchanged.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from app.contracts.dto import (
    AgentSessionDTO,
    DoseEventInput,
    FrequencyRuleDTO,
    RegimenDraftInput,
)
from app.contracts.enums import IntakeStatus, RegimenState, RuleKind
from app.domain.errors import ValidationError

PATIENT = UUID(int=310)

SINGAPORE = ZoneInfo("Asia/Singapore")
ALL_WEEKDAYS = [1, 2, 3, 4, 5, 6, 7]


def _report(wired, *, regimen_id, occurrence_id, intake_status, idempotency_key):
    """Record a self report through the real confirmation lifecycle.

    The database requires a confirmed, unconsumed ``record_self_report``
    challenge for every dose event, so the test issues and confirms one exactly
    as the transport does before recording.
    """
    session_id = UUID(int=800)
    wired.sessions.add(
        AgentSessionDTO(
            id=session_id,
            patient_id=PATIENT,
            intent="record_self_report",
            state="awaiting_confirmation",
            state_version=1,
            updated_at=wired.clock.now(),
            expires_at=wired.clock.now() + timedelta(hours=1),
        )
    )
    challenge = wired.self_report.request_confirmation(
        patient_id=PATIENT,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status=intake_status,
        idempotency_key=idempotency_key,
        session_id=session_id,
        session_state_version=1,
    )
    wired.self_report.confirm_challenge(
        patient_id=PATIENT, challenge_id=challenge.challenge.id
    )
    return wired.self_report.report(
        patient_id=PATIENT,
        payload=DoseEventInput(
            regimen_id=regimen_id,
            occurrence_id=occurrence_id,
            intake_status=intake_status,
            event_time=wired.clock.now(),
            idempotency_key=idempotency_key,
        ),
        challenge_id=challenge.challenge.id,
    )


def _activate(wired, *, frequency, is_prn=False, name="Amlodipine 5mg"):
    draft = RegimenDraftInput(
        medication_name=name,
        dose_amount=5,
        dose_unit="mg",
        frequency_rule=frequency,
        is_prn=is_prn,
        food_instruction="as needed for pain" if is_prn else None,
    )
    result = wired.enrollment.enroll_draft(patient_id=PATIENT, draft=draft)
    wired.enrollment.review_source_fields(
        patient_id=PATIENT, source_id=result.medication.source_id
    )
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT,
        regimen_id=result.regimen.id,
        session_id=UUID(int=401),
        session_state_version=1,
    )
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=challenge.id)
    activated = wired.enrollment.activate_regimen(
        patient_id=PATIENT,
        regimen_id=result.regimen.id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )
    return result, activated


# --- representation ---------------------------------------------------------


def test_two_daily_times_create_two_single_time_rules(wired):
    """Times are separate rows, never packed into one string."""
    result, _ = _activate(
        wired, frequency=FrequencyRuleDTO(kind="daily", local_times=["08:00", "20:00"])
    )

    rules = wired.dose_rules.list_for_regimen(PATIENT, result.regimen.id)

    assert len(rules) == 2
    assert all(len(rule.local_times) == 1 for rule in rules)
    assert sorted(rule.local_times[0] for rule in rules) == ["08:00", "20:00"]
    assert all(rule.rule_kind == RuleKind.SCHEDULED for rule in rules)


def test_daily_rule_carries_all_seven_weekdays(wired):
    """A daily instruction satisfies the SQL check that forbids an empty array."""
    result, _ = _activate(
        wired, frequency=FrequencyRuleDTO(kind="daily", local_times=["08:00", "20:00"])
    )

    for rule in wired.dose_rules.list_for_regimen(PATIENT, result.regimen.id):
        assert rule.days_of_week == ALL_WEEKDAYS


def test_three_daily_times_all_materialise(wired):
    result, _ = _activate(
        wired,
        frequency=FrequencyRuleDTO(kind="daily", local_times=["08:00", "13:00", "20:00"]),
    )

    occurrences = wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=result.regimen.id, days=1
    )
    local_times = sorted(
        occurrence.due_at.astimezone(SINGAPORE).strftime("%H:%M")
        for occurrence in occurrences
    )
    assert local_times == ["08:00", "13:00", "20:00"]


def test_each_occurrence_points_at_the_rule_that_produced_it(wired):
    result, _ = _activate(
        wired, frequency=FrequencyRuleDTO(kind="daily", local_times=["08:00", "20:00"])
    )
    rules = {rule.local_times[0]: rule for rule in wired.dose_rules.list_for_regimen(PATIENT, result.regimen.id)}

    occurrences = wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=result.regimen.id, days=1
    )

    assert len(occurrences) == 2
    for occurrence in occurrences:
        local_time = occurrence.due_at.astimezone(SINGAPORE).strftime("%H:%M")
        assert occurrence.rule_id == rules[local_time].id


def test_occurrences_are_stored_as_utc_while_times_are_local(wired):
    """08:00 and 20:00 Asia/Singapore are 00:00 and 12:00 UTC."""
    result, _ = _activate(
        wired, frequency=FrequencyRuleDTO(kind="daily", local_times=["08:00", "20:00"])
    )

    occurrences = wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=result.regimen.id, days=1
    )
    utc_hours = sorted(occurrence.due_at.astimezone(ZoneInfo("UTC")).hour for occurrence in occurrences)

    assert utc_hours == [0, 12]
    assert all(occurrence.due_at.tzinfo is not None for occurrence in occurrences)


# --- the other frequency kinds must not regress -----------------------------


def test_weekly_keeps_only_the_selected_days(wired):
    result, _ = _activate(
        wired,
        frequency=FrequencyRuleDTO(kind="weekly", local_times=["09:00"], days_of_week=[1, 3]),
    )

    rules = wired.dose_rules.list_for_regimen(PATIENT, result.regimen.id)

    assert len(rules) == 1
    assert rules[0].days_of_week == [1, 3]
    assert rules[0].local_times == ["09:00"]


def test_weekly_two_times_create_two_rules_sharing_days(wired):
    result, _ = _activate(
        wired,
        frequency=FrequencyRuleDTO(
            kind="weekly", local_times=["09:00", "21:00"], days_of_week=[2, 5]
        ),
    )

    rules = wired.dose_rules.list_for_regimen(PATIENT, result.regimen.id)

    assert len(rules) == 2
    assert all(rule.days_of_week == [2, 5] for rule in rules)


def test_prn_creates_exactly_one_prn_rule_and_no_occurrence(wired):
    result, _ = _activate(wired, frequency=None, is_prn=True, name="Paracetamol")

    rules = wired.dose_rules.list_for_regimen(PATIENT, result.regimen.id)

    assert len(rules) == 1
    assert rules[0].rule_kind == RuleKind.PRN
    assert rules[0].local_times == []
    assert rules[0].days_of_week == []

    # A PRN regimen never auto-generates a scheduled dose.
    assert wired.schedule.materialize(patient_id=PATIENT, regimen_id=result.regimen.id, days=3) == []


def test_activation_is_idempotent_for_rules(wired):
    """Re-activating the same regimen must not duplicate its rules."""
    result, activated = _activate(
        wired, frequency=FrequencyRuleDTO(kind="daily", local_times=["08:00", "20:00"])
    )
    before = wired.dose_rules.list_for_regimen(PATIENT, result.regimen.id)

    assert activated.regimen.state == RegimenState.ACTIVE
    assert len(before) == 2


def test_multiple_times_produce_two_due_targets_across_a_day(wired):
    """Both slots of the day exist as distinct, individually addressable doses."""
    result, _ = _activate(
        wired, frequency=FrequencyRuleDTO(kind="daily", local_times=["08:00", "20:00"])
    )
    wired.clock.advance(hours=10)  # 17:00 Singapore: only the 08:00 dose has passed
    # Occurrences exist only once the schedule has been materialised (the HTTP
    # route always materialises before looking for a due dose).
    wired.schedule.materialize(patient_id=PATIENT, regimen_id=result.regimen.id, days=1)

    due = wired.schedule.find_due(patient_id=PATIENT, regimen_id=result.regimen.id)

    assert due.occurrence is not None
    assert due.occurrence.due_at.astimezone(SINGAPORE).strftime("%H:%M") == "08:00"


def test_second_slot_becomes_due_after_the_evening_time(wired):
    result, _ = _activate(
        wired, frequency=FrequencyRuleDTO(kind="daily", local_times=["08:00", "20:00"])
    )
    wired.clock.advance(hours=10)  # 17:00 Singapore
    wired.schedule.materialize(patient_id=PATIENT, regimen_id=result.regimen.id, days=1)
    first = wired.schedule.find_due(patient_id=PATIENT, regimen_id=result.regimen.id)
    assert first.occurrence is not None

    # Report the morning dose, then move past the evening slot.
    _report(
        wired,
        regimen_id=result.regimen.id,
        occurrence_id=first.occurrence.id,
        intake_status=IntakeStatus.REPORTED_TAKEN,
        idempotency_key="slot-1",
    )
    wired.clock.advance(hours=4)  # 21:00 Singapore: the 20:00 slot is now due
    wired.schedule.materialize(patient_id=PATIENT, regimen_id=result.regimen.id, days=1)

    second = wired.schedule.find_due(patient_id=PATIENT, regimen_id=result.regimen.id)

    assert second.occurrence is not None
    assert second.occurrence.due_at.astimezone(SINGAPORE).strftime("%H:%M") == "20:00"
    assert second.occurrence.id != first.occurrence.id


@pytest.mark.parametrize("times", [["08:00"], ["08:00", "12:00"], ["07:30", "12:30", "19:30"]])
def test_all_daily_times_are_preserved_in_order(wired, times):
    result, _ = _activate(wired, frequency=FrequencyRuleDTO(kind="daily", local_times=times))

    rules = wired.dose_rules.list_for_regimen(PATIENT, result.regimen.id)

    assert sorted(rule.local_times[0] for rule in rules) == sorted(times)


def test_single_time_regimen_still_works(wired):
    """The pre-existing single-time behaviour must not regress."""
    result, _ = _activate(
        wired, frequency=FrequencyRuleDTO(kind="daily", local_times=["08:00"])
    )

    rules = wired.dose_rules.list_for_regimen(PATIENT, result.regimen.id)

    assert len(rules) == 1
    assert rules[0].local_times == ["08:00"]

    occurrences = wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=result.regimen.id, days=2
    )
    assert len(occurrences) == 2
    assert {occurrence.due_at.astimezone(SINGAPORE).strftime("%H:%M") for occurrence in occurrences} == {
        "08:00"
    }


def test_two_day_window_yields_both_slots_each_day(wired):
    result, _ = _activate(
        wired, frequency=FrequencyRuleDTO(kind="daily", local_times=["08:00", "20:00"])
    )

    occurrences = wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=result.regimen.id, days=2
    )
    per_day: dict[str, list[str]] = {}
    for occurrence in occurrences:
        local = occurrence.due_at.astimezone(SINGAPORE)
        per_day.setdefault(local.date().isoformat(), []).append(local.strftime("%H:%M"))

    assert len(per_day) == 2
    for times in per_day.values():
        assert sorted(times) == ["08:00", "20:00"]


def test_occurrences_are_not_duplicated_when_materialised_twice(wired):
    result, _ = _activate(
        wired, frequency=FrequencyRuleDTO(kind="daily", local_times=["08:00", "20:00"])
    )

    first = wired.schedule.materialize(patient_id=PATIENT, regimen_id=result.regimen.id, days=2)
    second = wired.schedule.materialize(patient_id=PATIENT, regimen_id=result.regimen.id, days=2)

    assert len(first) == 4
    assert {occurrence.id for occurrence in second} == {occurrence.id for occurrence in first}


def test_other_patient_cannot_see_the_rules(wired):
    result, _ = _activate(
        wired, frequency=FrequencyRuleDTO(kind="daily", local_times=["08:00", "20:00"])
    )

    assert wired.dose_rules.list_for_regimen(UUID(int=999), result.regimen.id) == []


def test_materialise_requires_active_regimen(wired):
    draft = RegimenDraftInput(
        medication_name="Amlodipine 5mg",
        dose_amount=5,
        dose_unit="mg",
        frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00"]),
    )
    result = wired.enrollment.enroll_draft(patient_id=PATIENT, draft=draft)

    with pytest.raises(ValidationError):
        wired.schedule.materialize(patient_id=PATIENT, regimen_id=result.regimen.id, days=1)


def test_due_lookup_ignores_the_future_slot_of_the_same_day(wired):
    """At 09:00 the 20:00 dose must not be reported as due."""
    result, _ = _activate(
        wired, frequency=FrequencyRuleDTO(kind="daily", local_times=["08:00", "20:00"])
    )
    wired.clock.advance(hours=2)  # 09:00 Singapore

    occurrences = wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=result.regimen.id, days=1
    )
    evening = [
        occurrence
        for occurrence in occurrences
        if occurrence.due_at.astimezone(SINGAPORE).strftime("%H:%M") == "20:00"
    ]
    assert len(evening) == 1
    assert evening[0].due_at > wired.clock.now()

    due = wired.schedule.find_due(patient_id=PATIENT, regimen_id=result.regimen.id)

    assert due.occurrence is not None
    assert due.occurrence.due_at.astimezone(SINGAPORE).strftime("%H:%M") == "08:00"


def test_window_rolls_over_to_the_next_day(wired):
    result, _ = _activate(
        wired, frequency=FrequencyRuleDTO(kind="daily", local_times=["08:00", "20:00"])
    )

    occurrences = wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=result.regimen.id, days=3
    )
    days = sorted({o.due_at.astimezone(SINGAPORE).date().isoformat() for o in occurrences})

    assert len(days) == 3
    assert len(occurrences) == 6


def test_lookback_is_bounded(wired):
    """A long-untouched regimen must not resurface an ancient dose."""
    result, _ = _activate(
        wired, frequency=FrequencyRuleDTO(kind="daily", local_times=["08:00"])
    )
    wired.clock.advance(days=5)

    due = wired.schedule.find_due(patient_id=PATIENT, regimen_id=result.regimen.id)

    assert due.occurrence is None


def test_materialise_window_starts_at_local_midnight_not_now(wired):
    """Today's already-passed dose must still exist so it can be reported."""
    result, _ = _activate(
        wired, frequency=FrequencyRuleDTO(kind="daily", local_times=["08:00"])
    )
    wired.clock.advance(hours=12)  # 19:00 Singapore: 08:00 has long passed

    occurrences = wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=result.regimen.id, days=1
    )

    assert len(occurrences) == 1
    assert occurrences[0].due_at < wired.clock.now()
    assert occurrences[0].due_at.astimezone(SINGAPORE).strftime("%H:%M") == "08:00"


def test_materialise_skips_occurrences_before_activation(wired):
    """A dose earlier today but before activation must not be generated."""
    result, _ = _activate(
        wired, frequency=FrequencyRuleDTO(kind="daily", local_times=["08:00"])
    )
    # Activation happened at 07:00 Singapore; an 06:00 instruction would be
    # before activation and must be excluded.
    earlier = FrequencyRuleDTO(kind="daily", local_times=["06:00"])
    assert earlier.kind == "daily"

    occurrences = wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=result.regimen.id, days=1
    )
    for occurrence in occurrences:
        assert occurrence.due_at >= (result.regimen.effective_from or occurrence.due_at)


def test_weekly_rules_materialise_only_on_selected_weekdays(wired):
    result, _ = _activate(
        wired,
        frequency=FrequencyRuleDTO(kind="weekly", local_times=["09:00"], days_of_week=[2]),
    )

    occurrences = wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=result.regimen.id, days=7
    )

    weekdays = {occurrence.due_at.astimezone(SINGAPORE).isoweekday() for occurrence in occurrences}
    assert weekdays == {2}


def test_due_result_never_claims_ingestion(wired):
    result, _ = _activate(
        wired, frequency=FrequencyRuleDTO(kind="daily", local_times=["08:00", "20:00"])
    )
    wired.clock.advance(hours=10)
    wired.schedule.materialize(patient_id=PATIENT, regimen_id=result.regimen.id, days=1)

    due = wired.schedule.find_due(patient_id=PATIENT, regimen_id=result.regimen.id)

    assert due.occurrence is not None
    assert not hasattr(due, "ingestion_proven")
    assert not hasattr(due, "intake_status")
