"""Read-only partial collection; no source review, business draft or activation."""

import re
import unicodedata
from decimal import Decimal
from uuid import UUID

from ..contracts.enrollment_workflow import EnrollmentFields, EnrollmentPreview
from ..domain.enrollment_inputs import normalise_enrollment_name, normalise_local_time
from ..domain.errors import ValidationError
from .enrollment import MedicationEnrollmentService


class EnrollmentPreviewService:
    def __init__(self, enrollment: MedicationEnrollmentService):
        self._enrollment = enrollment

    def preview_enrollment(self, owner: UUID, fields: EnrollmentFields) -> EnrollmentPreview:
        visible = fields.model_dump(mode="json", exclude_none=True)
        missing = [name for name in ("medication_name", "dose_amount", "dose_unit") if visible.get(name) in (None, "")]
        conflicts = []
        defaults = []
        schedule_missing = []
        rule = fields.frequency_rule
        if fields.is_prn:
            if rule is not None:
                raise ValidationError("PRN regimen cannot carry a scheduled frequency rule")
            if not str(fields.food_instruction or "").strip():
                schedule_missing.append("food_instruction")
        elif rule is None:
            schedule_missing.append("frequency_rule")
        else:
            for time in rule.local_times:
                normalise_local_time(time)
            if rule.kind == "daily":
                if (
                    not rule.local_times
                    or fields.times_per_day is not None
                    and len(rule.local_times) < fields.times_per_day
                ):
                    schedule_missing.append("frequency_local_times")
                elif fields.times_per_day is not None and len(rule.local_times) != fields.times_per_day:
                    conflicts.append("daily_count_mismatch")
            elif rule.kind == "weekly":
                if not rule.days_of_week:
                    schedule_missing.append("frequency_days_of_week")
                elif any(day < 1 or day > 7 for day in rule.days_of_week):
                    raise ValidationError("days_of_week values must be within 1..7")
                if not rule.local_times:
                    schedule_missing.append("frequency_local_times")
            elif rule.kind == "interval":
                if rule.every_hours is None:
                    schedule_missing.append("frequency_every_hours")
                elif rule.every_hours < 1:
                    raise ValidationError("interval rule requires every_hours >= 1")
                if fields.course_start_date is None:
                    schedule_missing.append("course_start_date")
                elif not rule.local_times:
                    defaults.append("interval_default_0800")
                if len(rule.local_times) > 1:
                    raise ValidationError("An interval schedule needs one first-dose time")
        if fields.course_end_date and not fields.course_start_date:
            schedule_missing.append("course_start_date")
        if fields.printed_course_days:
            schedule_missing.extend(
                name for name in ("course_start_date", "course_end_date") if getattr(fields, name) is None
            )
            if (
                fields.course_start_date
                and fields.course_end_date
                and (fields.course_end_date - fields.course_start_date).days + 1 != fields.printed_course_days
            ):
                conflicts.append("printed_course_mismatch")
        missing.extend(schedule_missing)
        normalized = None
        if fields.medication_name and not schedule_missing and not conflicts:
            normalized = self._enrollment.preview_draft(owner, fields.draft, dose_basis=fields.dose_basis)
        name = normalise_enrollment_name(fields.medication_name or "")
        candidates = (
            tuple(
                row
                for row in self._enrollment.list_medications(owner)
                if name and row.archived_at is None and normalise_enrollment_name(row.display_name) == name
            )
            if name
            else ()
        )

        def explicit_mg(text):
            match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*mg\s*", unicodedata.normalize("NFKC", text or ""), re.I)
            return Decimal(match[1]) if match and Decimal(match[1]) > 0 else None

        incoming = explicit_mg(fields.dose_basis.strength_text if fields.dose_basis else "")
        known_sources = {
            row.id: row
            for row in self._enrollment.get_sources(owner, [row.source_id for row in candidates if row.source_id])
        }
        recorded = []
        for row in candidates:
            source = known_sources.get(row.source_id)
            strength = source.dose_basis.strength_text if source and source.dose_basis else None
            if (
                not strength
                and source
                and source.extraction_evidence
                and len(source.extraction_evidence.candidates) == 1
            ):
                strength = source.extraction_evidence.candidates[0].product.strength
            recorded.append(explicit_mg(strength))
        distinct = bool(
            candidates and incoming is not None and all(value is not None and value != incoming for value in recorded)
        )
        if fields.distinct_product_confirmed and not distinct:
            conflicts.append("distinct_product_not_verified")
        if fields.existing_medication_id:
            if not any(row.id == fields.existing_medication_id for row in candidates):
                conflicts.append("stale_medication_selection")
        elif candidates and not (fields.distinct_product_confirmed and distinct):
            conflicts.append("possible_duplicate_medication")
        return EnrollmentPreview(
            distinct_product_available=distinct,
            missing_fields=tuple(dict.fromkeys(missing)),
            conflicts=tuple(conflicts),
            normalized_draft=normalized,
            review_fields=visible,
            medication_candidates=candidates,
            defaults=tuple(defaults),
        )
