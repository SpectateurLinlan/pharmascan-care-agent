"""RLS-enforced patient data-path regression tests (Session 3D).

** SIMULATED ** persistence with the same trust-boundary checks the real
PostgreSQL adapter enforces. The goal is to ensure a regression cannot silently
remove the patient-scoping that RLS relies on: if the application ever omits a
patient_id predicate, the in-memory patient-scoped read must return None/[], so
the transport still returns 404 rather than leaking another patient's data.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from app.contracts.dto import (
    AgentSessionDTO,
    DoseEventInput,
    FrequencyRuleDTO,
    RegimenDraftInput,
)
from app.contracts.enums import IntakeStatus

PATIENT = UUID(int=100)
OTHER_PATIENT = UUID(int=200)


def _activate(wired):
    """Enroll, review and activate a daily regimen for PATIENT."""
    result = wired.enrollment.enroll_draft(
        patient_id=PATIENT,
        draft=RegimenDraftInput(
            medication_name="Amlodipine 5mg",
            dose_amount=1,
            dose_unit="tablet",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00"]),
        ),
    )
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT,
        regimen_id=result.regimen.id,
        session_id=UUID(int=500),
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
    return result, activated


def _record(wired, regimen_id, occurrence_id):
    """Record a self report through the real confirmation lifecycle."""
    from datetime import timedelta

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
        intake_status=IntakeStatus.REPORTED_TAKEN,
        idempotency_key="rls-reg",
        session_id=session_id,
        session_state_version=1,
    )
    wired.self_report.confirm_challenge(patient_id=PATIENT, challenge_id=challenge.challenge.id)
    wired.self_report.report(
        patient_id=PATIENT,
        payload=DoseEventInput(
            regimen_id=regimen_id,
            occurrence_id=occurrence_id,
            intake_status=IntakeStatus.REPORTED_TAKEN,
            event_time=wired.clock.now(),
            idempotency_key="rls-reg",
        ),
        challenge_id=challenge.challenge.id,
    )


def test_cross_patient_regimen_lookup_returns_none(wired):
    """A regimen that exists for patient A is invisible to patient B."""
    _result, activated = _activate(wired)
    assert wired.regimens.get(OTHER_PATIENT, activated.regimen.id) is None


def test_cross_patient_medication_lookup_returns_none(wired):
    """A medication that exists for patient A is invisible to patient B."""
    result, _activated = _activate(wired)
    assert wired.medications.get(OTHER_PATIENT, result.medication.id) is None


def test_cross_patient_event_lookup_returns_none(wired):
    """A dose event that exists for patient A is invisible to patient B."""
    _result, activated = _activate(wired)
    wired.clock.advance(hours=10)
    wired.schedule.materialize(patient_id=PATIENT, regimen_id=activated.regimen.id, days=2)
    occurrence = wired.schedule.find_due(patient_id=PATIENT, regimen_id=activated.regimen.id).occurrence
    assert occurrence is not None
    _record(wired, activated.regimen.id, occurrence.id)

    assert wired.events.find_by_occurrence(OTHER_PATIENT, occurrence.id) is None
    assert (
        wired.events.list_for_patient(
            OTHER_PATIENT,
            wired.clock.now() - __import__("datetime").timedelta(days=1),
            wired.clock.now() + __import__("datetime").timedelta(days=1),
        )
        == []
    )


def test_cross_patient_history_is_refused(wired):
    """Patient B asking for history on A's regimen gets a 404-equivalent."""
    from app.domain.errors import NotFoundError

    _result, activated = _activate(wired)
    with pytest.raises(NotFoundError):
        wired.self_report.history(
            patient_id=OTHER_PATIENT,
            regimen_id=activated.regimen.id,
            window_start=wired.clock.now() - __import__("datetime").timedelta(days=1),
            window_end=wired.clock.now() + __import__("datetime").timedelta(days=1),
        )
