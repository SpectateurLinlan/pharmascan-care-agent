"""Closed independent patient care actions; review markers are not native rows."""

from contextlib import AbstractContextManager
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import Field, TypeAdapter, field_validator, model_validator

from .assistant_workflows import WorkflowDTO
from .long_term import (
    Barrier,
    BarrierInput,
    CareRepository,
    CareTask,
    CareTaskInput,
    StockInput,
    StockTransaction,
    TaskUpdate,
)
from .observations import Observation, ObservationInput, ObservationRepository
from .workflow_persistence import BusinessWriteReceipt, NativeWriteResult, PositiveRevision, WorkflowWriteBinding


class ConfirmedCareWrite(WorkflowDTO):
    binding: WorkflowWriteBinding
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def independent_patient_confirmation(cls, value):
        if value is not True:
            raise ValueError("Independent patient confirmation is required")
        return value


class SaveObservation(ConfirmedCareWrite):
    kind: Literal["save_observation"] = "save_observation"
    values: ObservationInput


class DeleteObservation(ConfirmedCareWrite):
    kind: Literal["delete_observation"] = "delete_observation"
    observation_id: UUID


class RecordStock(ConfirmedCareWrite):
    kind: Literal["stock"] = "stock"
    medication_id: UUID
    values: StockInput


class RecordBarrier(ConfirmedCareWrite):
    kind: Literal["barrier"] = "barrier"
    values: BarrierInput


class CreateFollowup(ConfirmedCareWrite):
    kind: Literal["create_followup"] = "create_followup"
    values: CareTaskInput


class UpdateFollowup(ConfirmedCareWrite):
    kind: Literal["update_followup"] = "update_followup"
    task_id: UUID
    expected_version: PositiveRevision
    values: TaskUpdate

    @model_validator(mode="after")
    def current_native_version(self):
        if self.expected_version != self.values.expected_version:
            raise ValueError("Native follow-up version differs from this review")
        return self


CareWriteCommand = Annotated[
    SaveObservation | DeleteObservation | RecordStock | RecordBarrier | CreateFollowup | UpdateFollowup,
    Field(discriminator="kind"),
]
CARE_WRITE_COMMAND = TypeAdapter(CareWriteCommand)
CareNativeResult = Observation | StockTransaction | Barrier | CareTask | None


class PrepareCareReview(WorkflowDTO):
    kind: Literal["prepare_care"] = "prepare_care"
    binding: WorkflowWriteBinding

    @model_validator(mode="after")
    def technical_review_only(self):
        ref = self.binding.prepared_ref
        if ref.kind != "care_review" or ref.id != self.binding.action_key or ref.version != 1:
            raise ValueError("Care preparation must own its technical review marker")
        return self


def care_command_payload(command: CareWriteCommand):
    result = command.model_dump(mode="json")
    if command.kind == "update_followup":
        # Native updates distinguish omitted fields from an explicit null/clear.
        result["values"] = command.values.model_dump(mode="json", exclude_unset=True)
    return result


class CareWorkflowWritePort(Protocol):
    def revision(self, owner: UUID) -> int: ...
    def lookup(self, owner: UUID, action_key: UUID) -> BusinessWriteReceipt | None: ...
    def apply(self, owner: UUID, command: CareWriteCommand) -> NativeWriteResult[CareNativeResult]: ...
    def read(self, owner: UUID, command: CareWriteCommand) -> NativeWriteResult[CareNativeResult]: ...
    def prepare(self, owner: UUID, command: PrepareCareReview) -> NativeWriteResult[None]: ...


class LocalObservationTransactionPort(ObservationRepository, Protocol):
    def local_transaction(self) -> AbstractContextManager[None]: ...
    def revision(self, owner: UUID) -> int: ...


class LocalCareTransactionPort(CareRepository, Protocol):
    def local_transaction(self) -> AbstractContextManager[None]: ...
    def revision(self, owner: UUID) -> int: ...
