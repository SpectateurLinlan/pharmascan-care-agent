"""Enrollment -> review -> activation tests (Gate 1).

All repositories are SIMULATED in-memory fakes. These tests prove the
application rules, not that PostgreSQL accepts the migration.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from app.contracts.dto import FrequencyRuleDTO, RegimenDraftInput
from app.contracts.enums import FieldName, IdentityStatus, RegimenState
from app.domain.errors import (
    ConfirmationRequiredError,
    IncompleteRegimenError,
    NotFoundError,
    SourceUnreviewedError,
    ValidationError,
)

PATIENT = UUID(int=100)
OTHER_PATIENT = UUID(int=200)


def _complete_draft() -> RegimenDraftInput:
    return RegimenDraftInput(
        medication_name="Amlodipine 5mg",
        dose_amount=1,
        dose_unit="tablet",
        frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00"]),
        route="oral",
        food_instruction="after food",
    )


def test_incomplete_draft_stays_pending_and_never_infers_a_dose(wired):
    draft = RegimenDraftInput(medication_name="Metformin")
    result = wired.enrollment.enroll_draft(patient_id=PATIENT, draft=draft)

    assert result.regimen.state == RegimenState.PENDING_CLARIFICATION
    assert result.regimen.dose_amount is None
    assert result.regimen.frequency_rule is None
    assert {m.field for m in result.missing_instructions} == {
        FieldName.DOSE_AMOUNT,
        FieldName.DOSE_UNIT,
        FieldName.FREQUENCY_RULE,
    }
    # Nothing was invented for the missing instructions.
    assert result.medication.identity_status == IdentityStatus.UNVERIFIED


def test_complete_draft_is_only_a_draft_until_confirmed(wired):
    result = wired.enrollment.enroll_draft(patient_id=PATIENT, draft=_complete_draft())

    assert result.regimen.state == RegimenState.DRAFT
    assert result.missing_instructions == []
    assert wired.regimens.find_active_for_medication(PATIENT, result.medication.id) is None


def test_activation_requires_reviewed_source_and_explicit_confirmation(wired):
    result = wired.enrollment.enroll_draft(patient_id=PATIENT, draft=_complete_draft())
    session_id = UUID(int=300)

    challenge, _token = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT,
        regimen_id=result.regimen.id,
        session_id=session_id,
        session_state_version=1,
    )

    # 0. An unreviewed source blocks activation before any confirmation check
    #    (source/evidence gate runs first by design).
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=challenge.id)
    with pytest.raises(SourceUnreviewedError):
        wired.enrollment.activate_regimen(
            patient_id=PATIENT,
            regimen_id=result.regimen.id,
            challenge_id=challenge.id,
            session_state="awaiting_confirmation",
            session_state_version=1,
        )

    # 1. Now review the source, but consume the confirmation so the explicit
    #    confirmation gate is the only thing left to fail.
    wired.enrollment.review_source_fields(
        patient_id=PATIENT, source_id=result.regimen.source_id
    )

    # 2. A fresh challenge that the patient has NOT confirmed -> blocked.
    unconfirmed, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT,
        regimen_id=result.regimen.id,
        session_id=UUID(int=305),
        session_state_version=1,
    )
    with pytest.raises(ConfirmationRequiredError):
        wired.enrollment.activate_regimen(
            patient_id=PATIENT,
            regimen_id=result.regimen.id,
            challenge_id=unconfirmed.id,
            session_state="awaiting_confirmation",
            session_state_version=1,
        )

    # 3. Confirm and activate successfully.
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=unconfirmed.id)
    activated = wired.enrollment.activate_regimen(
        patient_id=PATIENT,
        regimen_id=result.regimen.id,
        challenge_id=unconfirmed.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )
    assert activated.regimen.state == RegimenState.ACTIVE
    assert activated.regimen.effective_from is not None
    assert activated.regimen.confirmation_challenge_id == unconfirmed.id


def test_unreviewed_source_cannot_be_activated_even_with_confirmation(wired):
    result = wired.enrollment.enroll_draft(patient_id=PATIENT, draft=_complete_draft())
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT,
        regimen_id=result.regimen.id,
        session_id=UUID(int=301),
        session_state_version=1,
    )
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=challenge.id)

    with pytest.raises(SourceUnreviewedError):
        wired.enrollment.activate_regimen(
            patient_id=PATIENT,
            regimen_id=result.regimen.id,
            challenge_id=challenge.id,
            session_state="awaiting_confirmation",
            session_state_version=1,
        )


def test_incomplete_regimen_cannot_activate_even_when_reviewed_and_confirmed(wired):
    result = wired.enrollment.enroll_draft(
        patient_id=PATIENT, draft=RegimenDraftInput(medication_name="Metformin")
    )
    challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT,
        regimen_id=result.regimen.id,
        session_id=UUID(int=302),
        session_state_version=1,
    )
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=challenge.id)
    wired.enrollment.review_source_fields(patient_id=PATIENT, source_id=result.regimen.source_id)

    with pytest.raises(IncompleteRegimenError):
        wired.enrollment.activate_regimen(
            patient_id=PATIENT,
            regimen_id=result.regimen.id,
            challenge_id=challenge.id,
            session_state="awaiting_confirmation",
            session_state_version=1,
        )


def test_new_version_supersedes_previous_and_keeps_history(wired):
    first = wired.enrollment.enroll_draft(patient_id=PATIENT, draft=_complete_draft())
    first_challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT, regimen_id=first.regimen.id, session_id=UUID(int=303), session_state_version=1
    )
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=first_challenge.id)
    wired.enrollment.review_source_fields(patient_id=PATIENT, source_id=first.regimen.source_id)
    wired.enrollment.activate_regimen(
        patient_id=PATIENT,
        regimen_id=first.regimen.id,
        challenge_id=first_challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )

    # A second enrollment for the same medication would normally be a new
    # prescription; here we simulate a new version of the same medication.
    second = wired.enrollment.enroll_draft(
        patient_id=PATIENT,
        draft=RegimenDraftInput(
            medication_name="Amlodipine 5mg",
            dose_amount=2,
            dose_unit="tablet",
            frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00", "20:00"]),
        ),
    )
    second_challenge, _ = wired.enrollment.request_activation_challenge(
        patient_id=PATIENT, regimen_id=second.regimen.id, session_id=UUID(int=304), session_state_version=1
    )
    wired.enrollment.confirm_challenge(patient_id=PATIENT, challenge_id=second_challenge.id)
    wired.enrollment.review_source_fields(patient_id=PATIENT, source_id=second.regimen.source_id)

    # Different medication row -> activating does not retire the first one.
    activated = wired.enrollment.activate_regimen(
        patient_id=PATIENT,
        regimen_id=second.regimen.id,
        challenge_id=second_challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=1,
    )
    assert activated.regimen.state == RegimenState.ACTIVE
    assert activated.superseded_regimen_ids == []

    # The historical version is still readable and unchanged.
    original = wired.regimens.get(PATIENT, first.regimen.id)
    assert original is not None
    assert original.state == RegimenState.ACTIVE
    assert original.version_no == 1


def test_cross_patient_access_is_denied(wired):
    result = wired.enrollment.enroll_draft(patient_id=PATIENT, draft=_complete_draft())

    # Another patient cannot read the regimen, the medication or the source.
    assert wired.regimens.get(OTHER_PATIENT, result.regimen.id) is None
    assert wired.medications.get(OTHER_PATIENT, result.medication.id) is None
    assert wired.sources.get(OTHER_PATIENT, result.regimen.source_id) is None

    with pytest.raises(NotFoundError):
        wired.enrollment.review_source_fields(
            patient_id=OTHER_PATIENT, source_id=result.regimen.source_id
        )


def test_reviewed_source_is_immutable(wired):
    result = wired.enrollment.enroll_draft(patient_id=PATIENT, draft=_complete_draft())
    wired.enrollment.review_source_fields(patient_id=PATIENT, source_id=result.regimen.source_id)

    with pytest.raises(ValidationError):
        wired.enrollment.review_source_fields(
            patient_id=PATIENT, source_id=result.regimen.source_id
        )


def test_invalid_dose_and_prn_frequency_are_rejected(wired):
    with pytest.raises(ValidationError):
        wired.enrollment.enroll_draft(
            patient_id=PATIENT,
            draft=RegimenDraftInput(medication_name="X", dose_amount=-1, dose_unit="tablet"),
        )

    with pytest.raises(ValidationError):
        wired.enrollment.enroll_draft(
            patient_id=PATIENT,
            draft=RegimenDraftInput(
                medication_name="X",
                dose_amount=1,
                dose_unit="tablet",
                is_prn=True,
                frequency_rule=FrequencyRuleDTO(kind="daily", local_times=["08:00"]),
            ),
        )


def test_prn_draft_requires_indication_guidance_not_a_schedule(wired):
    """A PRN regimen has no schedule; the 'when to take it' instruction must
    still come from the patient, never be invented."""
    result = wired.enrollment.enroll_draft(
        patient_id=PATIENT,
        draft=RegimenDraftInput(
            medication_name="Paracetamol PRN", dose_amount=1, dose_unit="tablet", is_prn=True
        ),
    )
    assert result.regimen.state == RegimenState.PENDING_CLARIFICATION
    assert {m.field for m in result.missing_instructions} == {FieldName.FREQUENCY_RULE}
    assert result.regimen.frequency_rule is None
    assert result.regimen.is_prn is True

    # With the guidance supplied, the PRN draft becomes activatable.
    complete = wired.enrollment.enroll_draft(
        patient_id=PATIENT,
        draft=RegimenDraftInput(
            medication_name="Paracetamol PRN",
            dose_amount=1,
            dose_unit="tablet",
            is_prn=True,
            food_instruction="only when fever above 38C, max 3 times daily",
        ),
    )
    assert complete.regimen.state == RegimenState.DRAFT
    assert complete.missing_instructions == []
