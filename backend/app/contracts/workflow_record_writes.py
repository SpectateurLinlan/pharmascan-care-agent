"""Patient-confirmed native record commands; never an Agent backfill authority."""

from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import Field, TypeAdapter, field_validator, model_validator

from .assistant_workflows import WorkflowDTO
from .dto import DoseEventDTO, DoseEventInput, SelfReportChallengeResultDTO, SelfReportResultDTO
from .late_reports import LateReportChallenge, LateReportInput, LateReportRecord, ReportStatus
from .workflow_persistence import BusinessWriteReceipt, NativeWriteResult, WorkflowWriteBinding


class ConfirmedRecordWrite(WorkflowDTO):
    binding: WorkflowWriteBinding
    challenge_id: UUID
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def independent_patient_confirmation(cls, value):
        if value is not True:
            raise ValueError("Independent patient confirmation is required")
        return value


class DoseReportWrite(ConfirmedRecordWrite):
    kind: Literal["self_report"] = "self_report"
    values: DoseEventInput

    @model_validator(mode="after")
    def scheduled_occurrence(self):
        if self.values.occurrence_id is None:
            raise ValueError("A scheduled report needs its actual occurrence")
        if self.values.event_time.utcoffset() is None:
            raise ValueError("Report times must have a timezone")
        return self


class PrnReportWrite(ConfirmedRecordWrite):
    kind: Literal["prn_report"] = "prn_report"
    values: DoseEventInput

    @model_validator(mode="after")
    def no_scheduled_occurrence(self):
        if self.values.occurrence_id is not None:
            raise ValueError("A PRN report cannot invent a scheduled occurrence")
        if self.values.event_time.utcoffset() is None:
            raise ValueError("Report times must have a timezone")
        return self


class LateReportWrite(ConfirmedRecordWrite):
    kind: Literal["late_report"] = "late_report"
    occurrence_id: UUID
    values: LateReportInput

    @model_validator(mode="after")
    def first_report(self):
        if self.values.expected_report_id is not None:
            raise ValueError("Use the separate current correction review")
        return self


class CorrectionWrite(ConfirmedRecordWrite):
    kind: Literal["correction"] = "correction"
    occurrence_id: UUID
    values: LateReportInput

    @model_validator(mode="after")
    def current_report(self):
        if self.values.expected_report_id is None:
            raise ValueError("Correction requires the report the patient reviewed")
        return self


RecordWriteCommand = Annotated[
    DoseReportWrite | PrnReportWrite | LateReportWrite | CorrectionWrite,
    Field(discriminator="kind"),
]
RECORD_WRITE_COMMAND = TypeAdapter(RecordWriteCommand)
RecordNativeResult = SelfReportResultDTO | DoseEventDTO | LateReportRecord


class PrepareDoseReport(WorkflowDTO):
    kind: Literal["prepare_report"] = "prepare_report"
    binding: WorkflowWriteBinding
    session_id: UUID
    session_state_version: int = Field(strict=True, ge=1)
    operation_key: UUID
    intake_status: ReportStatus
    occurrence_id: UUID | None = None


class PrepareRecordReview(WorkflowDTO):
    """Select an existing target without issuing a challenge or choosing a report."""

    kind: Literal["prepare_review"] = "prepare_review"
    binding: WorkflowWriteBinding


class PrepareLateReport(WorkflowDTO):
    kind: Literal["prepare_late_report"] = "prepare_late_report"
    binding: WorkflowWriteBinding
    session_id: UUID
    session_state_version: int = Field(strict=True, ge=1)
    values: LateReportInput


RecordPreparationCommand = Annotated[
    PrepareRecordReview | PrepareDoseReport | PrepareLateReport, Field(discriminator="kind")
]
RECORD_PREPARATION_COMMAND = TypeAdapter(RecordPreparationCommand)
RecordPreparationNativeResult = SelfReportChallengeResultDTO | LateReportChallenge | None


class RecordWorkflowWritePort(Protocol):
    def revision(self, owner: UUID) -> int: ...
    def lookup(self, owner: UUID, action_key: UUID) -> BusinessWriteReceipt | None: ...
    def review(self, owner: UUID, task_id: UUID, revision: int) -> BusinessWriteReceipt: ...
    def read_result(self, owner: UUID, receipt: BusinessWriteReceipt) -> NativeWriteResult[RecordNativeResult]: ...
    def apply(self, owner: UUID, command: RecordWriteCommand) -> NativeWriteResult[RecordNativeResult]: ...
    def prepare(
        self, owner: UUID, command: RecordPreparationCommand
    ) -> NativeWriteResult[RecordPreparationNativeResult]: ...
