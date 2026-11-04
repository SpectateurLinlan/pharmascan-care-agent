"""Partial patient drafts; identity, confirmation and request IDs are not inputs."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from .assistant_workflows import WorkflowDTO
from .long_term import BarrierKind, CountUnit, StockInput, StockKind, TaskCategory
from .observations import Measurement


class CarePage(WorkflowDTO):
    page: int = Field(default=0, strict=True, ge=0, le=100000)


class CareReadFields(CarePage):
    medication_id: UUID | None = None
    days: Literal[7, 30, 366] = 30


class ObservationFields(WorkflowDTO):
    observation_id: UUID | None = None
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    occurred_at: AwareDatetime | None = None
    kind: Literal["note", "blood_pressure", "blood_glucose", "weight", "sleep", "mood"] = "note"
    value: float | None = Field(default=None, ge=0, le=10000)
    secondary_value: float | None = Field(default=None, ge=0, le=10000)
    unit: Literal["mmHg", "mmol/L", "mg/dL", "kg", "hours", "score"] | None = None
    severity: Literal["mild", "moderate", "severe"] | None = None
    notes: str | None = Field(default=None, max_length=1000)
    medication_id: UUID | None = None

    @model_validator(mode="after")
    def measurement(self):
        # A patient can still be collecting value/unit; complete measurements use the original contract.
        if (
            self.kind == "note"
            or self.value is not None
            and self.unit is not None
            and (self.kind != "blood_pressure" or self.secondary_value is not None)
        ):
            Measurement.model_validate(self.model_dump(include=set(Measurement.model_fields)))
        return self


class ObservationDeleteFields(CarePage):
    observation_id: UUID | None = None


class CareStockFields(CarePage):
    medication_id: UUID | None = None
    kind: StockKind = "count"
    quantity: float | None = Field(default=None, ge=-100000, le=100000)
    unit: CountUnit | None = None
    low_threshold: float = Field(default=7, ge=0, le=10000)
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def stock(self):
        if self.quantity is not None and self.unit is not None:
            StockInput(id=UUID(int=0), **self.model_dump(exclude={"page", "medication_id"}))
        return self


class CareBarrierFields(WorkflowDTO):
    category: BarrierKind | None = None
    occurred_at: AwareDatetime | None = None
    regimen_id: UUID | None = None
    description: str = Field(default="", max_length=1000)
    chosen_action: str = Field(default="", max_length=500)
    follow_up_task_id: UUID | None = None


class CareFollowupFields(WorkflowDTO):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    category: TaskCategory = "medication_review"
    due_at: AwareDatetime | None = None
    medication_id: UUID | None = None
    regimen_id: UUID | None = None
    notes: str = Field(default="", max_length=1000)
    reminder_minutes: int | None = Field(default=None, strict=True, ge=0, le=10080)


class CareFollowupChangeFields(CarePage):
    task_id: UUID | None = None
    expected_version: int | None = Field(default=None, strict=True, ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    category: TaskCategory | None = None
    due_at: AwareDatetime | None = None
    notes: str | None = Field(default=None, max_length=1000)
    status: Literal["open", "contacted", "deferred"] | None = None
    medication_id: UUID | None = None
    regimen_id: UUID | None = None
    clear_plan: bool = False
    reminder_minutes: int | None = Field(default=None, strict=True, ge=0, le=10080)
    disable_reminder: bool = False

    @model_validator(mode="after")
    def target_pair(self):
        if (self.task_id is None) != (self.expected_version is None):
            raise ValueError("Choose the follow-up and its current version together")
        if self.clear_plan and (self.medication_id or self.regimen_id):
            raise ValueError("Choose a linked plan or explicitly clear it")
        if self.disable_reminder and self.reminder_minutes is not None:
            raise ValueError("Choose an advance reminder or explicitly disable it")
        return self


CARE_READ_IDS = frozenset({"observation.list", "inventory.view", "barrier.list", "followup.list"})
CARE_CHANGE_STATUS = {
    "followup.contacted": "contacted",
    "followup.complete": "completed",
    "followup.defer": "deferred",
    "followup.cancel": "cancelled",
}
CARE_SCHEMAS = {
    **dict.fromkeys(CARE_READ_IDS, CareReadFields),
    "observation.add": ObservationFields,
    "observation.delete": ObservationDeleteFields,
    "observation.edit": ObservationFields,
    "inventory.count": CareStockFields,
    "barrier.add": CareBarrierFields,
    "followup.add": CareFollowupFields,
    **dict.fromkeys((*CARE_CHANGE_STATUS, "followup.edit"), CareFollowupChangeFields),
}
