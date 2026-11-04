"""Closed nonsecret settings commands; no Auth, delivery or verification authority."""

from contextlib import AbstractContextManager
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, Field, TypeAdapter, field_validator

from .assistant_workflows import WorkflowDTO
from .caregivers import CaregiverContact, CaregiverCreate, CaregiverDetails, CaregiverRepository
from .patient_feedback import FeedbackInput, FeedbackRepository, PatientFeedback
from .preferences import PreferenceRepository, Preferences, PreferenceUpdate
from .settings_workflow import PreferenceSnapshot
from .workflow_persistence import BusinessWriteReceipt, NativeWriteResult, WorkflowWriteBinding


class ConfirmedSettingsWrite(WorkflowDTO):
    binding: WorkflowWriteBinding
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def independent_confirmation(cls, value):
        if value is not True:
            raise ValueError("Independent patient confirmation is required")
        return value


class SavePreferences(ConfirmedSettingsWrite):
    kind: Literal["preferences"] = "preferences"
    values: PreferenceUpdate
    previous: PreferenceSnapshot


class CreateContact(ConfirmedSettingsWrite):
    kind: Literal["create_contact"] = "create_contact"
    values: CaregiverCreate


class EditContact(ConfirmedSettingsWrite):
    kind: Literal["edit_contact"] = "edit_contact"
    contact_id: UUID
    values: CaregiverDetails
    previous: CaregiverDetails
    previous_updated_at: AwareDatetime


class DeleteContact(ConfirmedSettingsWrite):
    kind: Literal["delete_contact"] = "delete_contact"
    contact_id: UUID
    previous: CaregiverDetails
    previous_updated_at: AwareDatetime


class SubmitFeedback(ConfirmedSettingsWrite):
    kind: Literal["feedback"] = "feedback"
    values: FeedbackInput


SettingsWriteCommand = Annotated[
    SavePreferences | CreateContact | EditContact | DeleteContact | SubmitFeedback, Field(discriminator="kind")
]
SETTINGS_WRITE_COMMAND = TypeAdapter(SettingsWriteCommand)
SettingsNativeResult = Preferences | CaregiverContact | PatientFeedback | None


def settings_command_body(command):
    """A partial native preference update must retain absent vs explicit fields."""
    body = command.model_dump(mode="json")
    if command.kind == "preferences":
        body["values"] = command.values.model_dump(mode="json", exclude_unset=True)
    return body


class PrepareSettingsReview(WorkflowDTO):
    kind: Literal["prepare_settings"] = "prepare_settings"
    binding: WorkflowWriteBinding


class SettingsWorkflowWritePort(Protocol):
    def revision(self, owner: UUID) -> int: ...
    def prepare(self, owner: UUID, command: PrepareSettingsReview) -> NativeWriteResult[SettingsNativeResult]: ...
    def apply(self, owner: UUID, command: SettingsWriteCommand) -> NativeWriteResult[SettingsNativeResult]: ...
    def read(self, owner: UUID, command: SettingsWriteCommand) -> NativeWriteResult[SettingsNativeResult]: ...
    def lookup(self, owner: UUID, action_key: UUID) -> BusinessWriteReceipt | None: ...


class LocalPreferencePort(PreferenceRepository, Protocol):
    def local_transaction(self) -> AbstractContextManager[None]: ...
    def revision(self, owner: UUID) -> int: ...


class LocalContactPort(CaregiverRepository, Protocol):
    def local_transaction(self) -> AbstractContextManager[None]: ...
    def revision(self, owner: UUID) -> int: ...


class LocalFeedbackPort(FeedbackRepository, Protocol):
    def local_transaction(self) -> AbstractContextManager[None]: ...
    def revision(self, owner: UUID) -> int: ...
