"""Deterministic safety & evidence policy (pure functions only).

This module is the application-level twin of the SQL guard triggers:
same rules, enforced twice (defense in depth). It NEVER calls an LLM,
never reads the clock, never touches I/O — so its decisions are
reproducible and unit-testable (AGENTS.md rules 21-23, 46-47 equivalent).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from ..contracts.dto import (
    FrequencyRuleDTO,
    PatientMedicationDTO,
    RegimenVersionDTO,
    SourceDocumentDTO,
    SourceFieldDTO,
)
from ..contracts.enums import (
    REVIEWED_STATUSES,
    FieldName,
    IdentityStatus,
    IntakeStatus,
    PolicyRuleId,
    RegimenState,
    SourceReviewStatus,
    VisualStatus,
)
from .errors import (
    ConfirmationExpiredError,
    ConfirmationRequiredError,
    DuplicateEventError,
    IncompleteRegimenError,
    NotFoundError,
    PolicyBlockedError,
    SourceUnreviewedError,
    StaleVersionError,
    ValidationError,
)

REQUIRED_SLOTS: tuple[FieldName, ...] = (
    FieldName.MEDICATION_NAME,
    FieldName.DOSE_AMOUNT,
    FieldName.DOSE_UNIT,
)

#: Source-field name carrying the patient's PRN indication/dose-condition text.
#: A PRN regimen has no schedule, but "when to take it" must still come from
#: the reviewed source — it is never inferred.
PRN_GUIDANCE_KEY = FieldName.FOOD_INSTRUCTION.value  # reused slot in the P0 slice
PRN_GUIDANCE_FIELD = FieldName.FOOD_INSTRUCTION


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    rule_id: PolicyRuleId | None = None
    reason: str = ""


def validate_frequency_rule(rule: FrequencyRuleDTO | None, *, is_prn: bool) -> None:
    """A scheduled regimen needs a frequency rule; a PRN one must not have one."""
    if is_prn and rule is not None:
        raise ValidationError("PRN regimen cannot carry a scheduled frequency rule")
    if not is_prn:
        if rule is None:
            raise ValidationError("Scheduled regimen requires a frequency rule")
        if rule.kind == "daily":
            if not rule.local_times:
                raise ValidationError("daily rule requires at least one local time")
        elif rule.kind == "weekly":
            if not rule.days_of_week or not rule.local_times:
                raise ValidationError("weekly rule requires days_of_week and local time")
            if not all(1 <= d <= 7 for d in rule.days_of_week):
                raise ValidationError("days_of_week values must be within 1..7")
        elif rule.kind == "interval":
            if not rule.every_hours or rule.every_hours < 1:
                raise ValidationError("interval rule requires every_hours >= 1")
        else:
            raise ValidationError(f"unsupported frequency kind: {rule.kind}")


def missing_required_instructions(
    draft_fields: dict[str, Any], *, is_prn: bool
) -> list[FieldName]:
    """Return required instructions that are still absent — they stay pending.

    Missing dose instructions must never be inferred or defaulted
    (AGENTS.md rule 23; DATA_MODEL 'missing ≠ missed').

    For a scheduled regimen the schedule itself is a required instruction.
    For a PRN regimen there is deliberately no schedule slot; instead the
    absent instruction is the free-text indication/dose-condition guidance the
    patient still has to supply (recorded as ``prn_guidance``).
    """
    missing: list[FieldName] = []
    for slot in REQUIRED_SLOTS:
        if draft_fields.get(slot.value) in (None, ""):
            missing.append(slot)
    if is_prn:
        # No scheduled frequency exists for PRN, but "when to take it" is
        # still an instruction we must not invent.
        if not str(draft_fields.get(PRN_GUIDANCE_KEY) or "").strip():
            missing.append(FieldName.FREQUENCY_RULE)
    else:
        if draft_fields.get(FieldName.FREQUENCY_RULE.value) is None:
            missing.append(FieldName.FREQUENCY_RULE)
    return missing


def check_activation_preconditions(
    *,
    medication: PatientMedicationDTO,
    source: SourceDocumentDTO | None,
    source_fields: list[SourceFieldDTO],
    missing_instructions: list[FieldName],
    now: datetime,
) -> None:
    """Raise the matching domain error when activation must be blocked."""
    if medication.archived_at is not None:
        raise StaleVersionError(f"Medication {medication.display_name} is archived")
    if medication.identity_status == IdentityStatus.UNVERIFIED:
        raise SourceUnreviewedError(
            "Medication identity is unverified; review the source document first"
        )
    if source is None:
        raise SourceUnreviewedError("Regimen draft has no source document")
    if source.review_status not in REVIEWED_STATUSES:
        raise SourceUnreviewedError(
            f"Source document review status is {source.review_status.value}; "
            "user_reviewed or professional_verified required"
        )
    unreviewed = [f for f in source_fields if f.review_status not in REVIEWED_STATUSES]
    if unreviewed:
        raise SourceUnreviewedError(
            f"{len(unreviewed)} source field(s) not reviewed"
        )
    if missing_instructions:
        names = ", ".join(m.value for m in missing_instructions)
        raise IncompleteRegimenError(
            f"Cannot activate: required instructions still missing: {names}"
        )


def check_regimen_state_transition(
    current: RegimenState, target: RegimenState
) -> PolicyDecision:
    """Legal state transitions (mirrors core_guard_regimen)."""
    if current in (RegimenState.ENDED, RegimenState.SUPERSEDED):
        return PolicyDecision(False, PolicyRuleId.CURRENT_VERSION_REQUIRED,
                              "historical regimen is immutable")
    if current == RegimenState.ACTIVE and target not in (
        RegimenState.ENDED,
        RegimenState.SUPERSEDED,
    ):
        return PolicyDecision(False, PolicyRuleId.CURRENT_VERSION_REQUIRED,
                              "active regimen can only be retired, never edited")
    if current in (RegimenState.DRAFT, RegimenState.PENDING_CLARIFICATION) and target not in (
        RegimenState.ACTIVE,
        RegimenState.PENDING_CLARIFICATION,
        RegimenState.DRAFT,
    ):
        return PolicyDecision(False, PolicyRuleId.CURRENT_VERSION_REQUIRED,
                              "only an active regimen can be retired")
    return PolicyDecision(True)


def check_dose_write_preconditions(
    *,
    regimen: RegimenVersionDTO,
    medication: PatientMedicationDTO | None,
    occurrence: object | None,
    occurrence_has_event: bool,
    intake_status: IntakeStatus,
    event_time: datetime,
) -> None:
    """Guards before persisting a self-report (mirrors core_guard_dose_event)."""
    if regimen.state != RegimenState.ACTIVE:
        raise StaleVersionError(
            f"Regimen {regimen.id} is {regimen.state.value}; only the current "
            "active regimen accepts dose reports"
        )
    if medication is None:
        raise NotFoundError("Medication for regimen not found")
    if medication.archived_at is not None:
        raise StaleVersionError("Medication is archived")
    if regimen.effective_from and event_time < regimen.effective_from:
        raise ValidationError("Self-report is before the regimen effective window")
    if regimen.effective_to and event_time >= regimen.effective_to:
        raise ValidationError("Self-report is after the regimen effective window")

    if regimen.is_prn:
        if occurrence is not None:
            raise ValidationError("PRN self-report must not reference a scheduled occurrence")
    else:
        if occurrence is None:
            raise ValidationError("Scheduled regimen requires a due occurrence")
        if occurrence_has_event:
            raise DuplicateEventError(
                "A self report already exists for this occurrence"
            )
        if getattr(occurrence, "status", None) == "closed":
            raise DuplicateEventError("Occurrence is already closed")


def check_confirmation(
    *,
    challenge: object | None,
    expected_action: str,
    expected_regimen_id: UUID,
    expected_occurrence_id: UUID | None,
    expected_intake_status: IntakeStatus | None,
    expected_idempotency_key: str | None,
    session_state: str,
    session_state_version: int,
    now: datetime,
) -> None:
    """Validate an explicit user confirmation before a protected write
    (mirrors core_consume_confirmation)."""
    if challenge is None:
        raise ConfirmationRequiredError("No confirmation challenge found")
    if not challenge.confirmed_at:  # type: ignore[attr-defined]
        raise ConfirmationRequiredError(
            "The patient has not explicitly confirmed this action yet"
        )
    if session_state != "awaiting_confirmation":
        raise ConfirmationRequiredError(
            f"Agent session state is {session_state!r}, expected 'awaiting_confirmation'"
        )
    if challenge.session_state_version != session_state_version:  # type: ignore[attr-defined]
        raise StaleVersionError("Confirmation was issued against a stale session state")
    if now >= challenge.expires_at:  # type: ignore[attr-defined]
        raise ConfirmationExpiredError("Confirmation expired")
    if challenge.consumed_at is not None:  # type: ignore[attr-defined]
        raise ConfirmationExpiredError("Confirmation already consumed")
    if challenge.action != expected_action:  # type: ignore[attr-defined]
        raise ConfirmationRequiredError("Confirmation action mismatch")
    if challenge.regimen_id != expected_regimen_id:  # type: ignore[attr-defined]
        raise ConfirmationRequiredError("Confirmation is bound to a different regimen")
    if challenge.occurrence_id != expected_occurrence_id:  # type: ignore[attr-defined]
        raise ConfirmationRequiredError("Confirmation is bound to a different occurrence")
    if challenge.intended_intake_status != expected_intake_status:  # type: ignore[attr-defined]
        raise ConfirmationRequiredError("Confirmation is bound to a different intake status")
    if (
        expected_idempotency_key is not None
        and challenge.idempotency_key != expected_idempotency_key  # type: ignore[attr-defined]
    ):
        raise ConfirmationRequiredError("Confirmation is bound to a different idempotency key")


def self_report_is_not_ingestion(intake_status: IntakeStatus, visual_status: VisualStatus) -> None:
    """Structural safety invariant: a self report never proves ingestion."""
    if intake_status == IntakeStatus.REPORTED_TAKEN and visual_status != VisualStatus.NOT_CHECKED:
        # Only a *validated* future visual path may set other statuses; the
        # P0 slice has no photo evidence at all, so this is always a bug.
        raise PolicyBlockedError(
            "P0 slice: self report must keep visual_status=not_checked",
            rule_id=PolicyRuleId.SELF_REPORT_NOT_INGESTION,
        )


def intake_status_from_patient_choice(choice: str) -> IntakeStatus:
    """Map the four patient-facing buttons to statuses; anything else is invalid.

    Accepts the UI labels shown to the patient ([Taken] [Check pill]
    [Not now] [Unsure]) as well as the snake_case API values, normalising
    case, surrounding whitespace, internal spaces and hyphens.
    """
    mapping = {
        "taken": IntakeStatus.REPORTED_TAKEN,
        "not_taken": IntakeStatus.REPORTED_NOT_TAKEN,
        "not_taken_yet": IntakeStatus.REPORTED_NOT_TAKEN,
        "not_now": IntakeStatus.REPORTED_NOT_TAKEN,
        "later": IntakeStatus.REPORTED_NOT_TAKEN,
        "unsure": IntakeStatus.UNSURE,
        "not_sure": IntakeStatus.UNSURE,
        "dont_know": IntakeStatus.UNSURE,
    }
    normalized = " ".join(choice.strip().lower().replace("-", " ").split())
    normalized = normalized.replace(" ", "_")
    try:
        return mapping[normalized]
    except KeyError:
        raise ValidationError(
            f"Unsupported patient choice {choice!r}; expected one of "
            "['Taken', 'Not now', 'Not taken', 'Unsure']"
        ) from None


def summarize_safety_notice(intake_status: IntakeStatus) -> str:
    """Patient-friendly wording: we never claim ingestion was proven."""
    if intake_status == IntakeStatus.REPORTED_TAKEN:
        return "Recorded as reported by you — this does not prove the medication was taken."
    if intake_status == IntakeStatus.UNSURE:
        return "Recorded as unsure — nothing was inferred about the actual intake."
    return "Recorded as reported by you."
