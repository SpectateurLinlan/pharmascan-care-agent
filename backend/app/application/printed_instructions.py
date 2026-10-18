"""Review proposals from printed instructions; no clinical schedule inference."""

import re

from ..contracts.dto import FrequencyRuleDTO, RegimenDraftInput
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
    elif parts.every_hours is not None and parts.every_hours.is_integer() and 1 <= parts.every_hours <= 720:
        # Preserve the printed interval, never invent its starting clock time/date.
        updates["frequency_rule"] = FrequencyRuleDTO(kind="interval", every_hours=int(parts.every_hours))
    # times_per_day/times_of_day/every_hours never become invented clock times.
    return RegimenDraftInput.model_validate({**draft.model_dump(), **updates})


def validate_printed_review(draft: RegimenDraftInput, parts: PrintedInstructions) -> None:
    # Some supported OCR responses retain an explicit clock only in the quoted
    # instructions. Reject a conflicting review; never silently replace it with
    # a default clock or derive one from morning/evening prose.
    printed_times = set()
    for hour, minute, period in re.findall(
        r"(?:\bat\s+|(?:在|于)\s*)([01]?\d|2[0-3]):([0-5]\d)(?!\d)(?:\s*([ap])\.?m\.?)?",
        parts.text,
        re.I,
    ):
        value = int(hour)
        if period:
            if not 1 <= value <= 12:
                raise ValidationError("The printed clock time is ambiguous; clarify the original instructions")
            value = value % 12 + (12 if period.lower() == "p" else 0)
        printed_times.add(f"{value:02d}:{minute}")
    if printed_times and not parts.as_needed:
        rule = draft.frequency_rule
        if not rule or set(rule.local_times) != printed_times:
            raise ValidationError("Review the explicit clock times printed in the original instructions")
    if parts.dose and parts.dose.amount_max is not None:
        raise ValidationError("A printed dose range needs clarification before a fixed-dose plan can be activated")
    if parts.dose and parts.dose.amount_max is None:
        if draft.dose_amount != parts.dose.amount or (parts.dose.unit and draft.dose_unit != parts.dose.unit):
            raise ValidationError("The reviewed dose conflicts with the printed instructions")
    if parts.as_needed and not draft.is_prn:
        raise ValidationError("The source says as needed; review the conflicting schedule")
    if parts.food and (draft.food_instruction or "").strip().casefold() != parts.food.replace("_", " "):
        raise ValidationError("The food instructions differ from the source; clarify before activation")
    if parts.every_hours is not None and not parts.as_needed:
        rule = draft.frequency_rule
        if (
            not rule
            or rule.kind != "interval"
            or rule.every_hours != parts.every_hours
            or len(rule.local_times) > 1
            or not draft.course_start_date
        ):
            raise ValidationError("Review the printed interval and first-dose date/time; blank time defaults to 08:00")
    if parts.times_per_day and not parts.as_needed and parts.every_hours is None:
        if draft.is_prn or not draft.frequency_rule or len(draft.frequency_rule.local_times) != parts.times_per_day:
            raise ValidationError("Review the printed daily frequency and explicitly choose the required times")
