"""Independent reminder preferences only; no notification or schedule authority."""

from contextlib import AbstractContextManager
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import Field, TypeAdapter, field_validator, model_validator

from .assistant_workflows import WorkflowDTO
from .preferences import Preferences, PreferenceUpdate
from .reminder_workflow import SnoozeFields
from .reminders import ReminderDTO, ReminderRepository
from .workflow_persistence import BusinessWriteReceipt, NativeWriteResult, WorkflowWriteBinding


class ConfirmedReminderWrite(WorkflowDTO):
    binding: WorkflowWriteBinding
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def independent_confirmation(cls, value):
        if value is not True:
            raise ValueError("Independent patient confirmation is required")
        return value


class SnoozeReminder(ConfirmedReminderWrite):
    kind: Literal["snooze"] = "snooze"
    values: SnoozeFields

    @model_validator(mode="after")
    def actual_occurrence(self):
        if self.values.occurrence_id is None or self.values.minutes is None or self.values.previous_timezone is None:
            raise ValueError("Use the existing occurrence and its current reminder/timezone snapshot")
        return self


class SaveReminderSettings(ConfirmedReminderWrite):
    kind: Literal["settings"] = "settings"
    values: PreferenceUpdate
    previous_enabled: bool = Field(strict=True)
    previous_lead_minutes: int = Field(strict=True, ge=0, le=120)
    previous_timezone: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def reminder_fields_only(self):
        if set(self.values.model_dump(exclude_none=True)) != {"reminders_enabled", "reminder_lead_minutes"}:
            raise ValueError("The reminder endpoint changes only the reviewed reminder settings")
        return self


class PrepareReminderReview(WorkflowDTO):
    kind: Literal["prepare_reminder"] = "prepare_reminder"
    binding: WorkflowWriteBinding


ReminderWriteCommand = Annotated[SnoozeReminder | SaveReminderSettings, Field(discriminator="kind")]
REMINDER_WRITE_COMMAND = TypeAdapter(ReminderWriteCommand)
ReminderNativeResult = ReminderDTO | Preferences | None


def reminder_command_body(command):
    body = command.model_dump(mode="json")
    if command.kind == "settings":
        body["values"] = command.values.model_dump(mode="json", exclude_unset=True)
    return body


class ReminderWorkflowWritePort(Protocol):
    def revision(self, owner: UUID) -> int: ...
    def prepare(self, owner: UUID, command: PrepareReminderReview) -> NativeWriteResult[ReminderNativeResult]: ...
    def apply(self, owner: UUID, command: ReminderWriteCommand) -> NativeWriteResult[ReminderNativeResult]: ...
    def read(self, owner: UUID, command: ReminderWriteCommand) -> NativeWriteResult[ReminderNativeResult]: ...
    def lookup(self, owner: UUID, action_key: UUID) -> BusinessWriteReceipt | None: ...


class LocalReminderPort(ReminderRepository, Protocol):
    def revision(self, owner: UUID) -> int: ...
    def local_transaction(self) -> AbstractContextManager[None]: ...
