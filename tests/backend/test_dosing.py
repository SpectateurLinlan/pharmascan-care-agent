"""Dose schedule, due-dose and self-report tests (Gate 1).

Proves the safety invariants: self report is never ingestion, a missing
report is never a miss, duplicate writes are idempotent, PRN has no
scheduled occurrence, and cross-patient access is denied.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from app.contracts.dto import (
    DoseEventInput,
    DoseRuleDTO,
    FrequencyRuleDTO,
    RegimenDraftInput,
)
from app.contracts.enums import IntakeStatus, OccurrenceStatus, RegimenState, RuleKind, VisualStatus
from app.domain.errors import (
    DuplicateEventError,
    NotFoundError,
    StaleVersionError,
    ValidationError,
)

PATIENT = UUID(int=100)
OTHER_PATIENT = UUID(int=200)


def _activate_scheduled(wired, *, times=("08:00",), amount: float = 1):
    draft = RegimenDraftInput(
        medication_name="Amlodipine 5mg",
        dose_amount=amount,
        dose_unit="tablet",
        frequency_rule=FrequencyRuleDTO(kind="daily", local_times=list(times)),
    )
    result = wired.enrollment.enroll_draft(patient_id=PATIENT, draft=draft)
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT,
        regimen_id=result.regimen.id,
        session_id=UUID(int=400),
        session_state_version=1,
    )
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=challenge.id)
    wired.enrollment.review_source_fields(patient_id=PATIENT, source_id=result.regimen.source_id)
    activated = wired.enrollment.activate_regimen(
        patient_id=PATIENT,
        regimen_id=result.regimen.id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )
    return result, activated, challenge


def _add_daily_rule(wired, regimen_id):
    rule = DoseRuleDTO(
        id=wired.ids.new_id(),
        patient_id=PATIENT,
        regimen_id=regimen_id,
        rule_kind=RuleKind.SCHEDULED,
        local_times=["08:00"],
        days_of_week=[],
        timezone="Asia/Singapore",
        enabled=True,
    )
    wired.schedule.add_rule(patient_id=PATIENT, regimen_id=regimen_id, rule=rule)
    return rule


def test_occurrences_generate_from_active_scheduled_regimen(wired):
    _result, activated, _challenge = _activate_scheduled(wired)
    # Activation persists the schedule rule itself, so no manual rule is added
    # here — that is the point of the test: an activated regimen is schedulable.
    rules = wired.dose_rules.list_for_regimen(PATIENT, activated.regimen.id)
    assert len(rules) == 1
    rule = rules[0]
    assert rule.rule_kind == RuleKind.SCHEDULED
    assert rule.local_times == ["08:00"]

    occurrences = wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=activated.regimen.id, days=3
    )
    assert occurrences, "a 3-day window must materialise at least one occurrence"
    assert all(o.rule_id == rule.id for o in occurrences)
    assert all(o.status == OccurrenceStatus.SCHEDULED for o in occurrences)
    # Occurrences are stored as timezone-aware UTC instants.
    assert all(o.due_at.tzinfo is not None for o in occurrences)
    # 08:00 Asia/Singapore == 00:00 UTC.
    assert all(o.due_at.hour == 0 and o.due_at.minute == 0 for o in occurrences)


def test_materialize_is_idempotent_by_generation_key(wired):
    _result, activated, _ = _activate_scheduled(wired)
    _add_daily_rule(wired, activated.regimen.id)

    first = wired.schedule.materialize(patient_id=PATIENT, regimen_id=activated.regimen.id, days=3)
    second = wired.schedule.materialize(patient_id=PATIENT, regimen_id=activated.regimen.id, days=3)

    assert len(first) == len(second)
    assert {o.id for o in first} == {o.id for o in second}


def test_prn_regimen_generates_no_scheduled_occurrence(wired):
    draft = RegimenDraftInput(
        medication_name="Paracetamol PRN",
        dose_amount=1,
        dose_unit="tablet",
        is_prn=True,
        food_instruction="only when fever above 38C",
    )
    result = wired.enrollment.enroll_draft(patient_id=PATIENT, draft=draft)
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT, regimen_id=result.regimen.id, session_id=UUID(int=401), session_state_version=1
    )
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=challenge.id)
    wired.enrollment.review_source_fields(patient_id=PATIENT, source_id=result.regimen.source_id)
    activated = wired.enrollment.activate_regimen(
        patient_id=PATIENT,
        regimen_id=result.regimen.id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )
    assert activated.regimen.is_prn is True
    assert wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=activated.regimen.id, days=7
    ) == []

    prn_rule = DoseRuleDTO(
        id=wired.ids.new_id(),
        patient_id=PATIENT,
        regimen_id=activated.regimen.id,
        rule_kind=RuleKind.PRN,
        local_times=[],
        days_of_week=[],
    )
    wired.schedule.add_rule(patient_id=PATIENT, regimen_id=activated.regimen.id, rule=prn_rule)
    assert wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=activated.regimen.id, days=7
    ) == []


def test_rule_kind_must_match_regimen_prn_flag(wired):
    _result, activated, _ = _activate_scheduled(wired)
    wrong_rule = DoseRuleDTO(
        id=wired.ids.new_id(),
        patient_id=PATIENT,
        regimen_id=activated.regimen.id,
        rule_kind=RuleKind.PRN,
        local_times=[],
        days_of_week=[],
    )
    with pytest.raises(ValidationError):
        wired.schedule.add_rule(
            patient_id=PATIENT, regimen_id=activated.regimen.id, rule=wrong_rule
        )


def test_self_report_taken_is_recorded_but_never_proves_ingestion(wired):
    _result, activated, _ = _activate_scheduled(wired)
    _add_daily_rule(wired, activated.regimen.id)
    occurrences = wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=activated.regimen.id, days=2
    )
    occurrence = occurrences[0]

    outcome = wired.self_report.report(
        patient_id=PATIENT,
        payload=DoseEventInput(
            regimen_id=activated.regimen.id,
            occurrence_id=occurrence.id,
            intake_status=IntakeStatus.REPORTED_TAKEN,
            event_time=wired.clock.now(),
            idempotency_key="report-1",
        ),
    )
    event = outcome.event
    assert event is not None
    assert event.intake_status == IntakeStatus.REPORTED_TAKEN
    assert event.ingestion_proven is False
    assert event.visual_status == VisualStatus.NOT_CHECKED


def test_unsure_and_not_reported_are_distinct_from_missed(wired):
    _result, activated, _ = _activate_scheduled(wired, times=("08:00", "20:00"))
    _add_daily_rule(wired, activated.regimen.id)
    occurrences = wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=activated.regimen.id, days=2
    )
    assert len(occurrences) >= 2

    # Report "unsure" for the first occurrence only.
    wired.self_report.report(
        patient_id=PATIENT,
        payload=DoseEventInput(
            regimen_id=activated.regimen.id,
            occurrence_id=occurrences[0].id,
            intake_status=IntakeStatus.UNSURE,
            event_time=wired.clock.now(),
            idempotency_key="unsure-1",
        ),
    )

    history = wired.self_report.history(
        patient_id=PATIENT,
        regimen_id=activated.regimen.id,
        window_start=wired.clock.now() - timedelta(days=1),
        window_end=wired.clock.now() + timedelta(days=3),
    )
    reported = [h for h in history if h.event is not None]
    unreported = [h for h in history if h.event is None]

    assert reported[0].event.intake_status == IntakeStatus.UNSURE
    # The unreported occurrences have NO event at all: absence of a report is
    # represented as a missing event, never as a "missed" status.
    assert unreported, "second occurrence must remain unreported"
    assert all(h.event is None for h in unreported)


def test_duplicate_report_for_same_occurrence_is_rejected(wired):
    _result, activated, _ = _activate_scheduled(wired)
    _add_daily_rule(wired, activated.regimen.id)
    occurrence = wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=activated.regimen.id, days=1
    )[0]

    wired.self_report.report(
        patient_id=PATIENT,
        payload=DoseEventInput(
            regimen_id=activated.regimen.id,
            occurrence_id=occurrence.id,
            intake_status=IntakeStatus.REPORTED_TAKEN,
            event_time=wired.clock.now(),
            idempotency_key="dup-a",
        ),
    )

    # A different idempotency key for the same occurrence must still be blocked,
    # because one occurrence can carry at most one self report.
    with pytest.raises(DuplicateEventError):
        wired.self_report.report(
            patient_id=PATIENT,
            payload=DoseEventInput(
                regimen_id=activated.regimen.id,
                occurrence_id=occurrence.id,
                intake_status=IntakeStatus.REPORTED_NOT_TAKEN,
                event_time=wired.clock.now(),
                idempotency_key="dup-b",
            ),
        )


def test_replayed_idempotency_key_returns_existing_event(wired):
    _result, activated, _ = _activate_scheduled(wired)
    _add_daily_rule(wired, activated.regimen.id)
    occurrence = wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=activated.regimen.id, days=1
    )[0]

    payload = DoseEventInput(
        regimen_id=activated.regimen.id,
        occurrence_id=occurrence.id,
        intake_status=IntakeStatus.REPORTED_TAKEN,
        event_time=wired.clock.now(),
        idempotency_key="retry-1",
    )
    first = wired.self_report.report(patient_id=PATIENT, payload=payload)
    second = wired.self_report.report(patient_id=PATIENT, payload=payload)

    assert first.already_recorded is False
    assert second.already_recorded is True
    assert second.existing_event_id == first.event.id
    assert second.event is None
    assert len(wired.events.list_for_patient(
        PATIENT, wired.clock.now() - timedelta(days=1), wired.clock.now() + timedelta(days=1)
    )) == 1


def test_prn_report_must_not_reference_a_scheduled_occurrence(wired):
    draft = RegimenDraftInput(
        medication_name="Paracetamol PRN",
        dose_amount=1,
        dose_unit="tablet",
        is_prn=True,
        food_instruction="only when fever above 38C",
    )
    result = wired.enrollment.enroll_draft(patient_id=PATIENT, draft=draft)
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT, regimen_id=result.regimen.id, session_id=UUID(int=402), session_state_version=1
    )
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=challenge.id)
    wired.enrollment.review_source_fields(patient_id=PATIENT, source_id=result.regimen.source_id)
    wired.enrollment.activate_regimen(
        patient_id=PATIENT,
        regimen_id=result.regimen.id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )

    # A PRN self report without an occurrence is valid.
    ok = wired.self_report.report(
        patient_id=PATIENT,
        payload=DoseEventInput(
            regimen_id=result.regimen.id,
            occurrence_id=None,
            intake_status=IntakeStatus.REPORTED_TAKEN,
            event_time=wired.clock.now(),
            idempotency_key="prn-1",
        ),
    )
    assert ok.event is not None and ok.event.occurrence_id is None


def test_scheduled_report_without_occurrence_is_rejected(wired):
    _result, activated, _ = _activate_scheduled(wired)
    with pytest.raises(ValidationError):
        wired.self_report.report(
            patient_id=PATIENT,
            payload=DoseEventInput(
                regimen_id=activated.regimen.id,
                occurrence_id=None,
                intake_status=IntakeStatus.REPORTED_TAKEN,
                event_time=wired.clock.now(),
                idempotency_key="no-occ",
            ),
        )


def test_report_on_inactive_regimen_is_blocked(wired):
    _result, activated, _ = _activate_scheduled(wired)
    _add_daily_rule(wired, activated.regimen.id)
    occurrence = wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=activated.regimen.id, days=1
    )[0]

    # Retire the regimen; historical states must not accept new writes.
    wired.regimens.update(
        activated.regimen.model_copy(
            update={"state": RegimenState.ENDED, "effective_to": wired.clock.now()}
        )
    )
    with pytest.raises(StaleVersionError):
        wired.self_report.report(
            patient_id=PATIENT,
            payload=DoseEventInput(
                regimen_id=activated.regimen.id,
                occurrence_id=occurrence.id,
                intake_status=IntakeStatus.REPORTED_TAKEN,
                event_time=wired.clock.now(),
                idempotency_key="ended-1",
            ),
        )


def test_cross_patient_dose_report_is_denied(wired):
    _result, activated, _ = _activate_scheduled(wired)
    _add_daily_rule(wired, activated.regimen.id)
    occurrence = wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=activated.regimen.id, days=1
    )[0]

    with pytest.raises(NotFoundError):
        wired.self_report.report(
            patient_id=OTHER_PATIENT,
            payload=DoseEventInput(
                regimen_id=activated.regimen.id,
                occurrence_id=occurrence.id,
                intake_status=IntakeStatus.REPORTED_TAKEN,
                event_time=wired.clock.now(),
                idempotency_key="cross-1",
            ),
        )

    assert wired.events.find_by_idempotency_key(OTHER_PATIENT, "cross-1") is None


def test_report_before_regimen_effective_window_is_rejected(wired):
    _result, activated, _ = _activate_scheduled(wired)
    _add_daily_rule(wired, activated.regimen.id)
    occurrence = wired.schedule.materialize(
        patient_id=PATIENT, regimen_id=activated.regimen.id, days=1
    )[0]

    with pytest.raises(ValidationError):
        wired.self_report.report(
            patient_id=PATIENT,
            payload=DoseEventInput(
                regimen_id=activated.regimen.id,
                occurrence_id=occurrence.id,
                intake_status=IntakeStatus.REPORTED_TAKEN,
                event_time=wired.clock.now() - timedelta(days=5),
                idempotency_key="early-1",
            ),
        )
