"""Typed unactivated aggregates and owner-scoped idempotent write boundary."""

from collections.abc import Callable
from typing import Protocol, TypeVar
from uuid import UUID

from pydantic import Field, model_validator

from .assistant_workflows import WorkflowDTO
from .dto import EnrollmentResultDTO, RegimenVersionDTO, SourceDocumentDTO
from .enrollment_workflow import EnrollmentFields
from .medication_plan_changes import PlanChangeDetails, PlanTargetState


class PlanChangeOperationInput(WorkflowDTO):
    action_key: UUID
    workflow_task_id: UUID
    workflow_revision: int = Field(ge=1)
    predecessor_id: UUID
    expected_version: int = Field(ge=1)
    expected_state: PlanTargetState
    fields: PlanChangeDetails


class EnrollmentOperationInput(WorkflowDTO):
    action_key: UUID
    fields: EnrollmentFields
    evidence_task_id: UUID | None = None
    workflow_task_id: UUID | None = None
    workflow_revision: int | None = Field(default=None, ge=1)


class PreparedEnrollment(WorkflowDTO):
    workflow_revision: int | None = Field(default=None, ge=1)
    source_candidate_index: int | None = Field(default=None, ge=0, le=19)
    attachment_ids: tuple[UUID, ...] = Field(default=(), max_length=10)
    workflow_task_id: UUID | None = None
    source: SourceDocumentDTO
    result: EnrollmentResultDTO
    create_medication: bool
    already_persisted: bool = False

    @model_validator(mode="after")
    def unactivated_owned_aggregate(self):
        result = self.result
        if result.regimen.state.value not in {"draft", "pending_clarification"}:
            raise ValueError("Preparation cannot activate a plan")
        owner = result.regimen.patient_id
        if self.source.patient_id != owner or result.medication.patient_id != owner:
            raise ValueError("Every prepared row must belong to the same patient")
        if result.regimen.source_id != self.source.id or result.regimen.patient_medication_id != result.medication.id:
            raise ValueError("Prepared aggregate references do not match")
        if any(row.patient_id != owner or row.source_id != self.source.id for row in result.source_fields):
            raise ValueError("Prepared fields must belong to the aggregate source")
        if not self.already_persisted and (self.source.reviewed_at or self.source.review_status.value != "extracted"):
            raise ValueError("Preparation cannot review a source")
        return self


class EnrollmentRecordRef(WorkflowDTO):
    source_candidate_index: int | None = Field(default=None, ge=0, le=19)
    attachment_ids: tuple[UUID, ...] = Field(default=(), max_length=10)
    workflow_task_id: UUID | None = None
    version_no: int = Field(default=1, ge=1)
    binding_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    regimen_id: UUID
    medication_id: UUID
    source_id: UUID


class EnrollmentWritePort(Protocol):
    def revision(self, owner: UUID) -> int: ...
    def lookup(self, owner: UUID, action_key: UUID) -> EnrollmentRecordRef | None: ...
    def for_regimen(self, owner: UUID, regimen_id: UUID) -> EnrollmentRecordRef | None: ...
    def for_attachment(self, owner: UUID, attachment_id: UUID) -> EnrollmentRecordRef | None: ...
    def create_once(
        self,
        owner: UUID,
        action_key: UUID,
        binding_digest: str,
        prepared: PreparedEnrollment,
        *,
        expected_revision: int,
    ) -> EnrollmentRecordRef: ...


T = TypeVar("T")


class EnrollmentReviewTransaction(Protocol):
    def run(self, owner: UUID, regimen: RegimenVersionDTO, write: Callable[[], T]) -> T: ...


class EnrollmentConfirmationGuard(Protocol):
    def run(self, owner: UUID, regimen: RegimenVersionDTO, write: Callable[[], T]) -> T: ...
    def bind_challenge(self, owner: UUID, regimen: RegimenVersionDTO, challenge_id: UUID) -> None: ...
    def run_challenge(
        self, owner: UUID, regimen: RegimenVersionDTO, challenge_id: UUID, write: Callable[[], T]
    ) -> T: ...
