"""Closed native medication transactions; preparation never substitutes confirmation."""

import hashlib
import json
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import Field, TypeAdapter, computed_field, field_validator, model_validator

from .assistant_workflows import WorkflowDTO
from .draft_deletion import DraftDeletionResult, DraftKind
from .dto import (
    ActivationResultDTO,
    ConfirmationChallengeDTO,
    PatientMedicationDTO,
    RegimenDraftInput,
    RegimenVersionDTO,
    SourceDocumentDTO,
    SourceFieldDTO,
)
from .enrollment_operations import EnrollmentRecordRef, PlanChangeOperationInput, PreparedEnrollment
from .medication_evidence import EnrollmentTask, MedicationImage, SourceLink
from .workflow_media_storage import VerifiedMediaOperationRef
from .workflow_persistence import BusinessWriteReceipt, NativeWriteResult, WorkflowWriteBinding
from .workflow_verification import VerifiedOperationRef


class PrepareMedication(WorkflowDTO):
    kind: Literal["prepare"] = "prepare"
    binding: WorkflowWriteBinding
    prepared: PreparedEnrollment
    binding_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class PrepareMedicationMaintenance(WorkflowDTO):
    kind: Literal["prepare_maintenance"] = "prepare_maintenance"
    binding: WorkflowWriteBinding


class ConfirmedMedicationWrite(WorkflowDTO):
    binding: WorkflowWriteBinding
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def patient_boolean(cls, value):
        if value is not True:
            raise ValueError("Independent patient confirmation is required")
        return value


class ReviewMedicationSource(ConfirmedMedicationWrite):
    kind: Literal["review_source"] = "review_source"
    source_id: UUID
    field_ids: tuple[UUID, ...] | None = Field(default=None, max_length=20)


class ReviewMedicationIdentity(ConfirmedMedicationWrite):
    kind: Literal["review_identity"] = "review_identity"


class RequestMedicationChallenge(WorkflowDTO):
    kind: Literal["request_challenge"] = "request_challenge"
    binding: WorkflowWriteBinding
    session_id: UUID
    session_state_version: int = Field(strict=True, ge=1)


class ActivateMedication(ConfirmedMedicationWrite):
    kind: Literal["activate"] = "activate"
    challenge_id: UUID
    session_state_version: int = Field(strict=True, ge=1)


class EndMedicationPlan(ConfirmedMedicationWrite):
    kind: Literal["end_plan"] = "end_plan"


class ChangeMedicationPlan(WorkflowDTO):
    kind: Literal["change_plan"] = "change_plan"
    binding: WorkflowWriteBinding
    values: PlanChangeOperationInput


class DeleteMedicationDraft(ConfirmedMedicationWrite):
    kind: Literal["delete_draft"] = "delete_draft"
    draft_kind: DraftKind


class PrepareSourceReview(WorkflowDTO):
    kind: Literal["prepare_source"] = "prepare_source"
    binding: WorkflowWriteBinding


class SaveSourceRegistration(ConfirmedMedicationWrite):
    kind: Literal["save_source"] = "save_source"
    attachment_id: UUID


class ReviewSourceRegistration(ConfirmedMedicationWrite):
    kind: Literal["review_registration"] = "review_registration"
    draft: RegimenDraftInput
    distinct_product_confirmed: bool = Field(strict=True)
    product_category: Literal["unknown", "POM", "P", "GSL", "supplement"] = "unknown"
    replace_active_plan: bool = Field(default=False, strict=True)


MedicationWriteCommand = Annotated[
    PrepareMedication
    | PrepareMedicationMaintenance
    | ReviewMedicationSource
    | ReviewMedicationIdentity
    | RequestMedicationChallenge
    | ActivateMedication
    | EndMedicationPlan
    | ChangeMedicationPlan
    | DeleteMedicationDraft
    | PrepareSourceReview
    | SaveSourceRegistration
    | ReviewSourceRegistration,
    Field(discriminator="kind"),
]
MEDICATION_WRITE_COMMAND = TypeAdapter(MedicationWriteCommand)
MedicationNativeResult = (
    EnrollmentRecordRef
    | SourceDocumentDTO
    | ConfirmationChallengeDTO
    | ActivationResultDTO
    | RegimenVersionDTO
    | DraftDeletionResult
    | EnrollmentTask
    | None
)


class SourcePublicationMetadata(WorkflowDTO):
    """Native metadata only; original/derived image bytes never enter Data API JSON."""

    source: SourceDocumentDTO
    fields: tuple[SourceFieldDTO, ...] = Field(max_length=20)
    medication: PatientMedicationDTO
    create_medication: bool = Field(strict=True)
    prior_task: EnrollmentTask | None
    task: EnrollmentTask
    image: MedicationImage
    link: SourceLink


class MaterializedMedicationSource(WorkflowDTO):
    metadata: SourcePublicationMetadata
    attachment_id: UUID
    original_verification: VerifiedOperationRef
    copy_verification: VerifiedMediaOperationRef
    duplicate: bool = Field(default=False, strict=True)


class MedicationWriteRequest(WorkflowDTO):
    command: MedicationWriteCommand
    prepared: PreparedEnrollment | None = None
    existing_review: EnrollmentTask | None = None
    materialized_source: MaterializedMedicationSource | None = None

    @computed_field
    @property
    def prepared_digest(self) -> str | None:
        if self.command.kind != "change_plan":
            return None
        # Preserve EnrollmentOperationService's existing native receipt format.
        payload = json.dumps(self.command.values.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    @model_validator(mode="after")
    def command_preparation(self):
        kind = self.command.kind
        if kind == "change_plan":
            valid = self.prepared is not None and self.existing_review is None and self.materialized_source is None
        elif kind == "review_registration":
            valid = (self.prepared is None) != (self.existing_review is None)
            valid = valid and self.materialized_source is None
        elif kind == "save_source":
            valid = self.materialized_source is not None and self.prepared is None and self.existing_review is None
        else:
            valid = self.prepared is None and self.existing_review is None and self.materialized_source is None
        if not valid:
            raise ValueError("Native preparation does not match this medication command")
        return self


class MedicationWritePreparationPort(Protocol):
    def prepare(self, owner: UUID, command: MedicationWriteCommand) -> MedicationWriteRequest: ...


class MedicationSourceMaterializationPort(Protocol):
    def materialize(self, owner: UUID, command: SaveSourceRegistration) -> MaterializedMedicationSource: ...


class MedicationWorkflowWritePort(Protocol):
    def revision(self, owner: UUID) -> int: ...
    def lookup(self, owner: UUID, action_key: UUID) -> BusinessWriteReceipt | None: ...
    def for_attachment(self, owner: UUID, attachment_id: UUID) -> EnrollmentRecordRef | None: ...
    def apply(self, owner: UUID, command: MedicationWriteCommand) -> NativeWriteResult[MedicationNativeResult]: ...
