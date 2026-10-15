"""Review proposals from printed instructions; no clinical schedule inference."""

from ..contracts.dto import RegimenDraftInput
from ..contracts.source_extraction import PrintedInstructions
from ..domain.errors import ValidationError


def apply_printed_parts(draft: RegimenDraftInput, parts: PrintedInstructions) -> RegimenDraftInput:
    updates: dict[str, object] = {}
    if parts.dose and parts.dose.amount > 0 and parts.dose.amount_max is None:
        updates.update(dose_amount=parts.dose.amount, dose_unit=parts.dose.unit)
    elif parts.dose and parts.dose.amount_max is not None:
        # Do not silently select one end of a printed dose range.
        updates.update(dose_amount=None, dose_unit=parts.dose.unit)
    if parts.food:
        updates["food_instruction"] = parts.food.replace("_", " ")
    if parts.as_needed:
        updates.update(is_prn=True, frequency_rule=None)
    # times_per_day/times_of_day/every_hours never become invented clock times.
    return RegimenDraftInput.model_validate({**draft.model_dump(), **updates})


def validate_printed_review(draft: RegimenDraftInput, parts: PrintedInstructions) -> None:
    if parts.dose and parts.dose.amount_max is not None:
        raise ValidationError("A printed dose range needs clarification before a fixed-dose plan can be activated")
    if parts.dose and parts.dose.amount_max is None:
        if draft.dose_amount != parts.dose.amount or (parts.dose.unit and draft.dose_unit != parts.dose.unit):
            raise ValidationError("The reviewed dose conflicts with the printed instructions")
    if parts.as_needed and not draft.is_prn:
        raise ValidationError("The source says as needed; review the conflicting schedule")
    if parts.food and (draft.food_instruction or "").strip().casefold() != parts.food.replace("_", " "):
        raise ValidationError("The food instructions differ from the source; clarify before activation")
    if parts.every_hours is not None:
        raise ValidationError(
            "Interval instructions require a separately reviewed supported schedule; no times inferred"
        )
    if parts.times_per_day and not parts.as_needed:
        if draft.is_prn or not draft.frequency_rule or len(draft.frequency_rule.local_times) != parts.times_per_day:
            raise ValidationError("Review the printed daily frequency and explicitly choose the required times")
