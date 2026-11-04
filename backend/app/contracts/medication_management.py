"""Closed read inputs and patient-visible plan projections; no confirmation tokens."""

from collections.abc import Callable
from typing import Literal, Protocol, TypeVar
from uuid import UUID

from pydantic import Field

from .assistant_workflows import WorkflowDTO
from .enrollment_workflow import EnrollmentFields

T = TypeVar("T")


class ClinicalMutationGuard(Protocol):
    def revision(self, owner: UUID) -> int: ...
    def run(self, owner: UUID, revision: int, write: Callable[[], T]) -> T: ...


class MedicationSetupFields(WorkflowDTO):
    page: int = Field(default=0, strict=True, ge=0, le=100000)


class MedicationPlanFields(MedicationSetupFields):
    medication_id: UUID | None = None


class MedicationPlanEndFields(WorkflowDTO):
    regimen_id: UUID | None = None
    expected_version: int | None = Field(default=None, strict=True, ge=1)


class MedicationDraftDeleteFields(WorkflowDTO):
    kind: Literal["draft", "source"] = "draft"
    target_id: UUID | None = None
    expected_version: int | None = Field(default=None, strict=True, ge=1)


class MedicationDraftResumeFields(MedicationSetupFields):
    regimen_id: UUID | None = None
    expected_version: int | None = Field(default=None, strict=True, ge=1)
    details: EnrollmentFields | None = None


MEDICATION_RECOVERY_SCHEMAS = {"medication.draft.resume": MedicationDraftResumeFields}


MEDICATION_READ_SCHEMAS = {
    "medication.plan.view": MedicationPlanFields,
    "medication.setup.list": MedicationSetupFields,
}

MEDICATION_MANAGEMENT_SCHEMAS = {
    **MEDICATION_READ_SCHEMAS,
    "medication.plan.end": MedicationPlanEndFields,
    "medication.draft.delete": MedicationDraftDeleteFields,
}
