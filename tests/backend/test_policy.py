"""Deterministic policy unit tests — pure functions, no I/O, no LLM.

These are the tests that prove the Safety Gate itself is deterministic and
enforces the medical-authority boundaries (AGENTS.md rules 21-23).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from app.contracts.dto import FrequencyRuleDTO, PatientMedicationDTO, RegimenVersionDTO, SourceDocumentDTO
from app.contracts.enums import (
    FieldName,
    IdentityStatus,
    IntakeStatus,
    PolicyRuleId,
    RegimenState,
    SourceReviewStatus,
    VisualStatus,
)
from app.domain import policy
from app.domain.errors import (
    ConfirmationExpiredError,
    ConfirmationRequiredError,
    DuplicateEventError,
    IncompleteRegimenError,
    SourceUnreviewedError,
    StaleVersionError,
    ValidationError,
)

NOW = datetime(2026, 10, 13, 1, 30, tzinfo=UTC)
PATIENT = UUID(int=100)


def _source(status: SourceReviewStatus) -> SourceDocumentDTO:
    return SourceDocumentDTO(
        id=UUID(int=1),
        patient_id=PATIENT,
        source_kind="user_manual",  # type: ignore[arg-type]
        review_status=status,
        reviewed_at=NOW if status != SourceReviewStatus.EXTRACTED else None,
    )


def _medication(identity: IdentityStatus = IdentityStatus.USER_REVIEWED_DOCUMENT) -> PatientMedicationDTO:
    return PatientMedicationDTO(
        id=UUID(int=2), patient_id=PATIENT, display_name="Amlodipine", identity_status=identity
    )


def _regimen(state=RegimenState.ACTIVE, is_prn=False) -> RegimenVersionDTO:
    return RegimenVersionDTO(
        id=UUID(int=3),
        patient_id=PATIENT,
        patient_medication_id=UUID(int=2),
        source_id=UUID(int=1),
        version_no=1,
        state=state,
        dose_amount=1,
        dose_unit="tablet",
        frequency_rule=None if is_prn else {"kind": "daily", "local_times": ["08:00"]},
        is_prn=is_prn,
        route=None,
        food_instruction=None,
        effective_from=NOW,
        effective_to=None,
        supersedes_id=None,
        confirmation_challenge_id=None,
        created_at=NOW,
    )


def test_frequency_rule_validation_is_strict_per_kind():
    policy.validate_frequency_rule(FrequencyRuleDTO(kind="daily", local_times=["08:00"]), is_prn=False)
    policy.validate_frequency_rule(
        FrequencyRuleDTO(kind="weekly", local_times=["08:00"], days_of_week=[1, 3]), is_prn=False
    )
    policy.validate_frequency_rule(FrequencyRuleDTO(kind="interval", every_hours=8), is_prn=False)
    policy.validate_frequency_rule(None, is_prn=True)

    with pytest.raises(ValidationError):
        policy.validate_frequency_rule(None, is_prn=False)
    with pytest.raises(ValidationError):
        policy.validate_frequency_rule(FrequencyRuleDTO(kind="daily"), is_prn=False)
    with pytest.raises(ValidationError):
        policy.validate_frequency_rule(
            FrequencyRuleDTO(kind="weekly", local_times=["08:00"], days_of_week=[0]), is_prn=False
        )
    with pytest.raises(ValidationError):
        policy.validate_frequency_rule(FrequencyRuleDTO(kind="interval"), is_prn=False)
    # A PRN regimen must not carry a schedule.
    with pytest.raises(ValidationError):
        policy.validate_frequency_rule(FrequencyRuleDTO(kind="daily", local_times=["08:00"]), is_prn=True)


def test_missing_instructions_are_reported_and_never_defaulted():
    missing = policy.missing_required_instructions({"medication_name": "X"}, is_prn=False)
    assert set(missing) == {
        FieldName.DOSE_AMOUNT,
        FieldName.DOSE_UNIT,
        FieldName.FREQUENCY_RULE,
    }
    complete = policy.missing_required_instructions(
        {
            "medication_name": "X",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_rule": {"kind": "daily", "local_times": ["08:00"]},
        },
        is_prn=False,
    )
    assert complete == []


def test_zero_or_negative_dose_is_treated_as_missing_not_defaulted():
    missing = policy.missing_required_instructions(
        {"medication_name": "X", "dose_amount": 0, "dose_unit": "tablet"}, is_prn=False
    )
    assert FieldName.FREQUENCY_RULE in missing


def test_activation_requires_reviewed_source_fields():
    with pytest.raises(SourceUnreviewedError):
        policy.check_activation_preconditions(
            medication=_medication(),
            source=_source(SourceReviewStatus.EXTRACTED),
            source_fields=[],
            missing_instructions=[],
            now=NOW,
        )

    unreviewed_field = SimpleNamespace(review_status=SourceReviewStatus.EXTRACTED)
    with pytest.raises(SourceUnreviewedError):
        policy.check_activation_preconditions(
            medication=_medication(),
            source=_source(SourceReviewStatus.USER_REVIEWED),
            source_fields=[unreviewed_field],
            missing_instructions=[],
            now=NOW,
        )


def test_activation_blocks_unverified_medication_identity():
    with pytest.raises(SourceUnreviewedError):
        policy.check_activation_preconditions(
            medication=_medication(IdentityStatus.UNVERIFIED),
            source=_source(SourceReviewStatus.USER_REVIEWED),
            source_fields=[],
            missing_instructions=[],
            now=NOW,
        )


def test_activation_blocks_archived_medication():
    archived = _medication().model_copy(update={"archived_at": NOW})
    with pytest.raises(StaleVersionError):
        policy.check_activation_preconditions(
            medication=archived,
            source=_source(SourceReviewStatus.USER_REVIEWED),
            source_fields=[],
            missing_instructions=[],
            now=NOW,
        )


def test_activation_blocks_missing_instructions():
    with pytest.raises(IncompleteRegimenError):
        policy.check_activation_preconditions(
            medication=_medication(),
            source=_source(SourceReviewStatus.USER_REVIEWED),
            source_fields=[],
            missing_instructions=[FieldName.DOSE_AMOUNT],
            now=NOW,
        )


def test_historical_and_active_regimen_transitions_are_restricted():
    # Historical states are immutable.
    for state in (RegimenState.ENDED, RegimenState.SUPERSEDED):
        decision = policy.check_regimen_state_transition(state, RegimenState.ACTIVE)
        assert decision.allowed is False
        assert decision.rule_id == PolicyRuleId.CURRENT_VERSION_REQUIRED

    # An active regimen can only be retired, not edited back to draft/active.
    assert policy.check_regimen_state_transition(
        RegimenState.ACTIVE, RegimenState.SUPERSEDED
    ).allowed
    assert policy.check_regimen_state_transition(
        RegimenState.ACTIVE, RegimenState.DRAFT
    ).allowed is False

    # A draft may become active or remain a draft.
    assert policy.check_regimen_state_transition(RegimenState.DRAFT, RegimenState.ACTIVE).allowed
    assert policy.check_regimen_state_transition(
        RegimenState.PENDING_CLARIFICATION, RegimenState.ACTIVE
    ).allowed


def test_self_report_never_proves_ingestion_structurally():
    # The only allowed combination in the P0 slice.
    policy.self_report_is_not_ingestion(IntakeStatus.REPORTED_TAKEN, VisualStatus.NOT_CHECKED)

    # Any attempt to attach a visual verdict to a self report is blocked.
    with pytest.raises(Exception) as excinfo:
        policy.self_report_is_not_ingestion(
            IntakeStatus.REPORTED_TAKEN, VisualStatus.VISUALLY_CONSISTENT
        )
    assert excinfo.value.rule_id == PolicyRuleId.SELF_REPORT_NOT_INGESTION


def test_patient_choice_mapping_covers_four_buttons_and_rejects_unknown():
    assert policy.intake_status_from_patient_choice("Taken") == IntakeStatus.REPORTED_TAKEN
    assert policy.intake_status_from_patient_choice("Not now") == IntakeStatus.REPORTED_NOT_TAKEN
    assert policy.intake_status_from_patient_choice("not_taken") == IntakeStatus.REPORTED_NOT_TAKEN
    assert policy.intake_status_from_patient_choice("Unsure") == IntakeStatus.UNSURE
    with pytest.raises(ValidationError):
        policy.intake_status_from_patient_choice("took_double_dose")


def test_safety_notice_never_claims_ingestion():
    taken = policy.summarize_safety_notice(IntakeStatus.REPORTED_TAKEN)
    assert "does not prove" in taken
    unsure = policy.summarize_safety_notice(IntakeStatus.UNSURE)
    assert "unsure" in unsure.lower()


def test_duplicate_occurrence_report_is_blocked_by_policy():
    with pytest.raises(DuplicateEventError):
        policy.check_dose_write_preconditions(
            regimen=_regimen(),
            medication=_medication(),
            occurrence=SimpleNamespace(status="scheduled", id=UUID(int=9)),
            occurrence_has_event=True,
            intake_status=IntakeStatus.REPORTED_TAKEN,
            event_time=NOW,
        )


def test_closed_occurrence_cannot_be_reported_again():
    with pytest.raises(DuplicateEventError):
        policy.check_dose_write_preconditions(
            regimen=_regimen(),
            medication=_medication(),
            occurrence=SimpleNamespace(status="closed", id=UUID(int=9)),
            occurrence_has_event=False,
            intake_status=IntakeStatus.REPORTED_TAKEN,
            event_time=NOW,
        )


def test_inactive_regimen_rejects_dose_writes():
    with pytest.raises(StaleVersionError):
        policy.check_dose_write_preconditions(
            regimen=_regimen(state=RegimenState.ENDED),
            medication=_medication(),
            occurrence=SimpleNamespace(status="scheduled", id=UUID(int=9)),
            occurrence_has_event=False,
            intake_status=IntakeStatus.REPORTED_TAKEN,
            event_time=NOW,
        )


def test_prn_write_must_not_reference_an_occurrence():
    with pytest.raises(ValidationError):
        policy.check_dose_write_preconditions(
            regimen=_regimen(is_prn=True),
            medication=_medication(),
            occurrence=SimpleNamespace(status="scheduled", id=UUID(int=9)),
            occurrence_has_event=False,
            intake_status=IntakeStatus.REPORTED_TAKEN,
            event_time=NOW,
        )


def _challenge(**overrides):
    base = dict(
        confirmed_at=NOW,
        session_state_version=1,
        expires_at=NOW + timedelta(minutes=10),
        consumed_at=None,
        action="record_self_report",
        regimen_id=UUID(int=3),
        occurrence_id=UUID(int=9),
        intended_intake_status=IntakeStatus.REPORTED_TAKEN,
        idempotency_key="k1",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _check(challenge, **overrides):
    kwargs = dict(
        challenge=challenge,
        expected_action="record_self_report",
        expected_regimen_id=UUID(int=3),
        expected_occurrence_id=UUID(int=9),
        expected_intake_status=IntakeStatus.REPORTED_TAKEN,
        expected_idempotency_key="k1",
        session_state="awaiting_confirmation",
        session_state_version=1,
        now=NOW,
    )
    kwargs.update(overrides)
    policy.check_confirmation(**kwargs)


def test_confirmation_requires_explicit_user_action():
    with pytest.raises(ConfirmationRequiredError):
        _check(_challenge(confirmed_at=None))


def test_confirmation_expiry_and_single_use_are_enforced():
    with pytest.raises(ConfirmationExpiredError):
        _check(_challenge(expires_at=NOW - timedelta(seconds=1)))
    with pytest.raises(ConfirmationExpiredError):
        _check(_challenge(consumed_at=NOW))


def test_confirmation_binding_to_action_regimen_occurrence_and_payload():
    with pytest.raises(ConfirmationRequiredError):
        _check(_challenge(action="activate_regimen"))
    with pytest.raises(ConfirmationRequiredError):
        _check(_challenge(regimen_id=UUID(int=99)))
    with pytest.raises(ConfirmationRequiredError):
        _check(_challenge(occurrence_id=UUID(int=88)))
    with pytest.raises(ConfirmationRequiredError):
        _check(_challenge(intended_intake_status=IntakeStatus.UNSURE))
    with pytest.raises(ConfirmationRequiredError):
        _check(_challenge(idempotency_key="different"))


def test_stale_session_state_is_rejected():
    with pytest.raises(StaleVersionError):
        _check(_challenge(session_state_version=0))
    with pytest.raises(ConfirmationRequiredError):
        _check(_challenge(), session_state="collecting")


def test_confirmation_without_challenge_is_rejected():
    with pytest.raises(ConfirmationRequiredError):
        _check(None)
