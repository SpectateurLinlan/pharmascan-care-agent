"""Pure input normalization shared by preview and the existing draft writer."""

import unicodedata
from datetime import datetime

from ..contracts.dose_display import DoseBasis, DoseDisplayInput
from ..contracts.dto import IntervalAnchor, RegimenDraftInput
from . import policy
from .dose_display import dose_display
from .errors import ValidationError
from .interval_schedule import interval_moments


def normalise_enrollment_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def normalise_local_time(value: str) -> str:
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValidationError(f"invalid local time {value!r}; expected HH:MM")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValidationError(f"local time {value!r} is out of range")
    return f"{hour:02d}:{minute:02d}"


def normalise_enrollment_draft(
    draft: RegimenDraftInput, *, timezone: str, now: datetime, dose_basis: DoseBasis | None = None
) -> RegimenDraftInput:
    if not draft.medication_name.strip():
        raise ValidationError("medication_name is required")
    if draft.frequency_rule is not None and draft.frequency_rule.kind == "interval":
        frequency = draft.frequency_rule
        if draft.course_start_date is None:
            raise ValidationError("Enter the first-dose date for an interval schedule")
        if len(frequency.local_times) > 1:
            raise ValidationError("An interval schedule needs one first-dose time")
        time = normalise_local_time(frequency.local_times[0]) if frequency.local_times else "08:00"
        anchor = IntervalAnchor(
            local_date=draft.course_start_date,
            local_time=time,
            time_source="patient_entered" if frequency.local_times else "default_0800",
        )
        frequency = frequency.model_copy(update={"local_times": [time], "interval_anchor": anchor})
        interval_moments(frequency.model_dump(mode="json"), now, now, timezone)
        draft = draft.model_copy(update={"frequency_rule": frequency})
    if dose_basis and draft.dose_amount is not None and draft.dose_unit:
        display = dose_display(
            DoseDisplayInput(basis=dose_basis, units_per_dose=draft.dose_amount, dose_unit=draft.dose_unit)
        )
        if display.status == "conflict":
            raise ValidationError(display.reason)
    if draft.dose_amount is not None and draft.dose_amount <= 0:
        raise ValidationError("dose_amount must be > 0")
    if draft.frequency_rule is not None:
        policy.validate_frequency_rule(draft.frequency_rule, is_prn=draft.is_prn)
        for local_time in draft.frequency_rule.local_times:
            normalise_local_time(local_time)
    return draft
