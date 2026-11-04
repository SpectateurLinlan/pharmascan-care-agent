"""Patient instruction changes only; identity, linkage and confirmation are derived."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, model_serializer, model_validator

from .assistant_workflows import WorkflowDTO
from .dto import FrequencyRuleDTO, RegimenVersionDTO
from .enrollment_workflow import EnrollmentFields, EnrollmentPreview

PlanTargetState = Literal["active", "ended", "superseded"]


class PlanChangeDetails(WorkflowDTO):
    dose_amount: float | None = Field(default=None, strict=True, gt=0)
    dose_unit: str | None = Field(default=None, min_length=1, max_length=40)
    frequency_rule: FrequencyRuleDTO | None = None
    is_prn: bool | None = None
    route: str | None = Field(default=None, max_length=40)
    food_instruction: str | None = Field(default=None, max_length=1000)
    course_start_date: date | None = None
    course_end_date: date | None = None
    times_per_day: int | None = Field(default=None, strict=True, ge=1, le=24)

    @model_validator(mode="after")
    def server_derived_anchor(self):
        if self.frequency_rule and self.frequency_rule.interval_anchor is not None:
            raise ValueError("The first-dose anchor is derived from the reviewed date and time")
        return self

    @model_serializer(mode="plain")
    def serialize_patch(self):
        # An explicit null clears a recorded optional instruction. Omission keeps
        # the original. Do not let parent exclude_none collapse these meanings.
        return {name: getattr(self, name) for name in type(self).model_fields if name in self.model_fields_set}


class PlanChangeFields(WorkflowDTO):
    regimen_id: UUID | None = None
    expected_version: int | None = Field(default=None, strict=True, ge=1)
    expected_state: PlanTargetState | None = None
    page: int = Field(default=0, strict=True, ge=0, le=100000)
    details: PlanChangeDetails | None = None

    @model_validator(mode="after")
    def paired_selection(self):
        if len({self.regimen_id is None, self.expected_version is None, self.expected_state is None}) != 1:
            raise ValueError("Choose the plan, its version and recorded state together")
        if self.details is not None and self.regimen_id is None:
            raise ValueError("Choose the recorded plan before changing instructions")
        return self


class PlanChangePreview(WorkflowDTO):
    target: RegimenVersionDTO
    fields: EnrollmentFields
    preview: EnrollmentPreview
    changed: bool
