"""Partial enrollment inputs are collection, never reviewed clinical facts."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from .assistant_workflows import WorkflowDTO
from .dose_display import DoseBasis
from .dto import FrequencyRuleDTO, PatientMedicationDTO, RegimenDraftInput


class EnrollmentFields(WorkflowDTO):
    method: Literal["manual", "photo"] | None = None
    medication_name: str | None = Field(default=None, min_length=1, max_length=160)
    dose_amount: float | None = Field(default=None, strict=True, gt=0)
    dose_unit: str | None = Field(default=None, min_length=1, max_length=40)
    frequency_rule: FrequencyRuleDTO | None = None
    is_prn: bool | None = None
    route: str | None = Field(default=None, max_length=40)
    food_instruction: str | None = Field(default=None, max_length=1000)
    course_start_date: date | None = None
    course_end_date: date | None = None
    dose_basis: DoseBasis | None = None
    times_per_day: int | None = Field(default=None, strict=True, ge=1, le=24)
    existing_medication_id: UUID | None = None
    distinct_product_confirmed: bool | None = None
    source_attachment_id: UUID | None = None
    source_candidate_index: int | None = Field(default=None, ge=0, le=19, strict=True)
    printed_course_days: int | None = Field(default=None, ge=1, le=365, strict=True)
    page_photo_previewed: bool | None = None

    @model_validator(mode="after")
    def retain_source_review_boundary(self):
        if self.dose_basis and self.dose_basis.patient_checked:
            raise ValueError("Source review must use the independent patient review")
        if self.medication_name is not None and not self.medication_name.strip():
            raise ValueError("Medication name cannot be blank")
        if self.course_end_date and self.course_start_date and self.course_end_date < self.course_start_date:
            raise ValueError("Course end cannot precede the start date")
        return self

    @property
    def draft(self) -> RegimenDraftInput | None:
        if self.medication_name is None:
            return None
        return RegimenDraftInput.model_validate(
            self.model_dump(
                exclude={
                    "method",
                    "dose_basis",
                    "times_per_day",
                    "existing_medication_id",
                    "distinct_product_confirmed",
                    "source_attachment_id",
                    "source_candidate_index",
                    "printed_course_days",
                    "page_photo_previewed",
                },
                exclude_none=True,
            )
        )


class EnrollmentPreview(WorkflowDTO):
    distinct_product_available: bool = False
    missing_fields: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    normalized_draft: RegimenDraftInput | None = None
    review_fields: dict[str, JsonValue]
    medication_candidates: tuple[PatientMedicationDTO, ...] = ()
    defaults: tuple[str, ...] = ()
