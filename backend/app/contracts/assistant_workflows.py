"""Public workflow inputs; identity and confirmation remain server-owned."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .assistant_explanations import ExplanationStep
from .chat_photo import ChatPhotoContext
from .long_term import StockInput
from .medication_dialogue import MedicationSelection
from .medication_names import NameSelection
from .navigation_context import NavigationInput

if TYPE_CHECKING:
    from ..agent.orchestrator import AgentReply


class WorkflowDTO(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class WorkflowEvent(WorkflowDTO):
    event_id: UUID
    expected_revision: int = Field(ge=1)
    kind: Literal[
        "provide_fields",
        "choose_method",
        "select_candidate",
        "review_source",
        "prepare_confirmation",
        "report_business_result",
        "retry",
        "resume",
        "pause",
        "cancel_save",
        "allow_save",
        "cancel_task",
    ]
    values: dict[str, object] = Field(default_factory=dict)


class EphemeralPayload(WorkflowDTO):
    capability_id: str = Field(pattern=r"^[a-z]+(?:\.[a-z]+)*$")
    fields: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded_payload(self):
        if len(self.model_dump_json().encode("utf-8")) > 16384:
            raise ValueError("Workflow input exceeds the 16KiB UTF-8 budget")
        return self


class EmptyFields(WorkflowDTO):
    pass


class EnrollmentStartFields(WorkflowDTO):
    method: Literal["manual", "photo"] | None = None


class StockFields(WorkflowDTO):
    medication_id: UUID | None = None
    quantity: float
    unit: Literal["tablet", "capsule"]
    kind: Literal["count", "refill", "adjustment", "lost", "discarded", "damaged"] = "count"
    low_threshold: float = 7
    note: str = ""

    @model_validator(mode="after")
    def use_existing_stock_validation(self):
        StockInput(id=UUID(int=0), **self.model_dump(exclude={"medication_id"}))
        return self


def validate_workflow_values(capability_id: str, values: dict[str, object]) -> BaseModel:
    # Schema implementations grow with their adapters, never via a generic
    # fallback that would accept unimplemented or executable client fields.
    from ..domain.errors import ValidationError
    from .care_workflow import CARE_SCHEMAS
    from .conversation_workflow import CONVERSATION_SCHEMAS, SUPPORT_SCHEMAS
    from .dose_report_workflow import REPORT_SCHEMAS
    from .enrollment_workflow import EnrollmentFields
    from .image_comparison import CompareFields
    from .knowledge_workflow import KnowledgeFields
    from .late_report_workflow import LATE_REVIEW_SCHEMAS
    from .media_workflow import MEDIA_CHANGE_SCHEMAS, MEDIA_READ_SCHEMAS, PdfUploadFields, PhotoUploadFields
    from .medication_management import MEDICATION_MANAGEMENT_SCHEMAS, MEDICATION_RECOVERY_SCHEMAS
    from .medication_plan_changes import PlanChangeFields
    from .medication_records import RECORD_READ_SCHEMAS
    from .medication_sources import SOURCE_SCHEMAS
    from .reminder_workflow import NOTIFICATION_DEVICE_SCHEMAS, REMINDER_READ_SCHEMAS, REMINDER_WRITE_SCHEMAS
    from .settings_workflow import ACCOUNT_SCHEMAS, CONTACT_SCHEMAS, PREFERENCE_SCHEMAS
    from .source_preview_workflow import SourcePreviewFields

    schemas = {
        **CONVERSATION_SCHEMAS,
        **SUPPORT_SCHEMAS,
        **ACCOUNT_SCHEMAS,
        **CONTACT_SCHEMAS,
        **PREFERENCE_SCHEMAS,
        **NOTIFICATION_DEVICE_SCHEMAS,
        **REMINDER_WRITE_SCHEMAS,
        "inventory.count": StockFields,
        "medication.enroll": EnrollmentFields,
        **MEDICATION_MANAGEMENT_SCHEMAS,
        **MEDICATION_RECOVERY_SCHEMAS,
        **SOURCE_SCHEMAS,
        "medication.plan.change": PlanChangeFields,
        **RECORD_READ_SCHEMAS,
        **REPORT_SCHEMAS,
        **LATE_REVIEW_SCHEMAS,
        "medication.knowledge": KnowledgeFields,
        **CARE_SCHEMAS,
        **MEDIA_READ_SCHEMAS,
        **MEDIA_CHANGE_SCHEMAS,
        "gallery.photo.add": PhotoUploadFields,
        "library.pdf.add": PdfUploadFields,
        "image.compare": CompareFields,
        "source.preview": SourcePreviewFields,
        **REMINDER_READ_SCHEMAS,
    }
    schema = schemas.get(capability_id)
    if schema is None:
        raise ValidationError("Input schema unavailable for this assistant capability")
    return schema.model_validate(values)


SaveMode = Literal["allowed", "ephemeral"]
StorageState = Literal["ephemeral", "saving", "saved", "save_failed", "cleanup_pending"]
WorkflowState = Literal[
    "choose_method",
    "collecting",
    "validating",
    "ready_for_review",
    "awaiting_confirmation",
    "executing",
    "completed",
    "failed_recoverable",
    "suspended",
    "cancelled",
    "outcome_unknown",
]


class BusinessRef(WorkflowDTO):
    kind: Literal[
        "medication",
        "regimen",
        "enrollment_task",
        "source",
        "dose_event",
        "dose_occurrence",
        "late_report",
        "care_review",
        "media_review",
        "reminder_review",
        "reminder_action",
        "settings_review",
        "settings_action",
        "agent_session",
        "conversation_cleanup",
        "observation",
        "stock",
        "barrier",
        "care_task",
        "contact",
        "file",
        "conversation",
        "feedback",
        "preference",
    ]
    id: UUID
    version: int | None = Field(default=None, ge=1)


class WorkflowContext(WorkflowDTO):
    owner: UUID
    task_id: UUID
    capability_id: str = Field(pattern=r"^[a-z]+(?:\.[a-z]+)*$")
    revision: int = Field(ge=1)
    language: Literal["en", "zh"] = "en"
    timezone: str = "Asia/Singapore"
    save_mode: SaveMode = "allowed"


class ChoiceOption(WorkflowDTO):
    value: str = Field(min_length=1, max_length=100)
    label_key: str = Field(min_length=1, max_length=200)
    label_text: str | None = Field(default=None, max_length=200)


class ChoiceAction(WorkflowDTO):
    kind: Literal["choice"] = "choice"
    action_id: str = Field(max_length=100)
    options: tuple[ChoiceOption, ...] = Field(min_length=1, max_length=10)


class FieldFormAction(WorkflowDTO):
    kind: Literal["fields"] = "fields"
    schema_id: str = Field(max_length=120)
    field_names: tuple[str, ...] = Field(max_length=30)


class UploadAction(WorkflowDTO):
    kind: Literal["upload"] = "upload"
    action_id: Literal["source_image", "reference_image", "library_pdf"]
    processing_consent_required: bool = True


class ExistingReviewAction(WorkflowDTO):
    kind: Literal["existing_review"] = "existing_review"
    component_key: Literal[
        "existing_activation",
        "existing_source_review",
        "existing_self_report",
        "existing_late_report",
        "existing_care_review",
        "existing_observation_review",
        "existing_draft_delete",
        "existing_plan_end",
        "existing_media_management",
        "existing_preference_review",
        "existing_reminder_review",
        "existing_contact_review",
        "existing_feedback_review",
    ]
    owned_ref: BusinessRef
    expected_version: int = Field(ge=1)


class ResumeTaskAction(WorkflowDTO):
    kind: Literal["resume_task"] = "resume_task"
    owned_ref: BusinessRef
    expected_version: int = Field(ge=1)


class SecureAccountAction(WorkflowDTO):
    kind: Literal["secure_account"] = "secure_account"
    action: Literal["status", "login", "link", "password", "signout"]


class DownloadAction(WorkflowDTO):
    kind: Literal["download"] = "download"
    capability_id: Literal["reminder.calendar.export", "library.pdf.download"]
    owned_ref: BusinessRef | None = None


class DeviceAction(WorkflowDTO):
    kind: Literal["device"] = "device"
    action: Literal["camera", "upload", "microphone", "notification_permission", "speech_playback"]


class NavigateAction(WorkflowDTO):
    kind: Literal["navigate"] = "navigate"
    route: Literal[
        "today",
        "medicines",
        "records",
        "me",
        "assistant",
        "care-tasks",
        "adherence-barriers",
        "medication-review",
        "check",
        "check-result",
        "label",
        "manual",
        "edit-medication",
        "medicine-history",
        "medication-inventory",
        "unfinished",
        "past-medicines",
        "gallery",
        "medicine-detail",
        "health-notes",
        "medication-records",
        "summary-week",
        "summary-month",
        "summary-course",
        "profile",
        "account",
        "caregivers",
        "settings",
        "reminder-settings",
        "language-settings",
        "accessibility",
        "privacy",
        "conversations",
        "about",
        "feedback",
        "help",
    ]


class ConversationAction(WorkflowDTO):
    kind: Literal["conversation"] = "conversation"
    action: Literal["resume", "new", "clear"]
    conversation_id: UUID | None = None


UIAction = Annotated[
    ChoiceAction
    | FieldFormAction
    | UploadAction
    | ExistingReviewAction
    | ResumeTaskAction
    | SecureAccountAction
    | DownloadAction
    | DeviceAction
    | NavigateAction
    | ConversationAction,
    Field(discriminator="kind"),
]


class WorkflowTask(WorkflowDTO):
    id: UUID
    owner: UUID
    workspace_id: UUID
    conversation_id: UUID | None = None
    capability_id: str
    capability_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)
    state: WorkflowState = "collecting"
    save_mode: SaveMode = "allowed"
    storage_state: StorageState = "saving"
    fields: dict[str, JsonValue] = Field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()
    attachment_ids: tuple[UUID, ...] = Field(default=(), max_length=10)
    business_refs: tuple[BusinessRef, ...] = Field(default=(), max_length=20)
    updated_at: datetime

    @model_validator(mode="after")
    def bounded_fields(self):
        if len(json.dumps(self.fields, ensure_ascii=False).encode("utf-8")) > 16384:
            raise ValueError("Workflow fields exceed the persistence budget")
        return self


class WorkflowView(WorkflowDTO):
    input_fields: dict[str, JsonValue] | None = None
    task_id: UUID
    workspace_id: UUID | None = None
    conversation_id: UUID | None = None
    revision: int = Field(ge=1)
    capability_id: str
    state: WorkflowState
    save_mode: SaveMode
    storage_state: StorageState
    prompt_key: str
    visible_fields: dict[str, JsonValue] = Field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()
    actions: tuple[UIAction, ...] = ()
    explanations: tuple[ExplanationStep, ...] = ()
    result_ref: BusinessRef | None = None
    cleanup_pending: bool = False
    protected_originals: bool = False


class AttachmentRef(WorkflowDTO):
    id: UUID
    task_id: UUID
    original_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_type: Literal["image/png", "image/jpeg", "application/pdf"]
    extraction_status: Literal[
        "pending", "consent_required", "succeeded", "failed", "interrupted", "not_requested"
    ] = "pending"


class WorkflowAttachmentReader(Protocol):
    def assets(self, owner: UUID, task_id: UUID) -> tuple[AttachmentRef, ...]: ...


class Preparation(WorkflowDTO):
    input_fields: dict[str, JsonValue] | None = None
    workflow_state: WorkflowState = "collecting"
    prompt_key: str = "assistant.workflow.collecting"
    actions: tuple[UIAction, ...] = ()
    view_fields: dict[str, JsonValue] = Field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()
    pending_review: ExistingReviewAction | None = None
    result_ref: BusinessRef | None = None


class OperationResult(WorkflowDTO):
    state: Literal["succeeded", "failed", "pending", "outcome_unknown"]
    business_ref: BusinessRef | None = None
    reason: str | None = None


class WorkflowUpdate(WorkflowDTO):
    state: WorkflowState
    save_mode: SaveMode
    storage_state: StorageState
    fields: dict[str, JsonValue]
    missing_fields: tuple[str, ...] = ()
    attachment_ids: tuple[UUID, ...] = ()
    business_refs: tuple[BusinessRef, ...] = ()


class ControlReceipt(WorkflowDTO):
    task_id: UUID
    owner: UUID
    revision: int = Field(ge=1)
    capability_id: str
    workspace_id: UUID | None = None
    conversation_id: UUID | None = None
    status: Literal["idle", "processing", "interrupted", "suspended", "cancelled", "completed"] = "idle"
    mode: SaveMode
    revoked: bool = False
    processing_event_id: UUID | None = None
    lease_until: datetime | None = None


class ActionReceipt(WorkflowDTO):
    clinical_revision: int | None = Field(default=None, ge=0)
    action_key: UUID
    owner: UUID
    task_id: UUID
    capability_id: str
    binding_revision: int = Field(ge=1)
    state: Literal["pending", "succeeded", "failed", "outcome_unknown"]
    business_ref: BusinessRef | None = None
    safe_reason: str | None = None
    updated_at: datetime


class CapabilityAdapter(Protocol):
    def prepare(
        self,
        context: WorkflowContext,
        values: BaseModel,
        assets: tuple[AttachmentRef, ...],
        results: tuple[BusinessRef, ...] = (),
    ) -> Preparation: ...
    def observe(self, context: WorkflowContext, result_ref: BusinessRef) -> OperationResult: ...


class CapabilityTaskResumer(Protocol):
    def resume_target(self, context: WorkflowContext, values: BaseModel) -> UUID: ...


PatientWriteResult = TypeVar("PatientWriteResult")


class CapabilityPatientActionGuard(Protocol):
    def run_patient_action(
        self, context: WorkflowContext, result_ref: BusinessRef, write: Callable[[], PatientWriteResult]
    ) -> PatientWriteResult: ...


class CapabilityPatientResultReader(Protocol):
    def read_patient_result(
        self, context: WorkflowContext, result_ref: BusinessRef, values: BaseModel | None = None
    ) -> BusinessRef: ...


class CapabilityBusinessWriter(Protocol):
    def reconcile(self, context: WorkflowContext, action_key: UUID) -> BusinessRef | None: ...
    def prepare_once(
        self, context: WorkflowContext, values: BaseModel, assets: tuple[AttachmentRef, ...], action_key: UUID
    ) -> BusinessRef: ...
    def revise_inputs(self, context: WorkflowContext, result_ref: BusinessRef) -> dict[str, JsonValue]: ...


class WorkflowRepository(Protocol):
    def bind_conversation(
        self,
        owner: UUID,
        task_id: UUID,
        expected_revision: int,
        conversation_id: UUID,
    ) -> WorkflowTask: ...
    def create(
        self,
        task: WorkflowTask,
        *,
        suspend_foreground: bool = False,
        event_id: UUID | None = None,
        request_digest: str | None = None,
    ) -> WorkflowTask: ...
    def get(self, owner: UUID, task_id: UUID) -> WorkflowTask: ...
    def cas(
        self,
        owner: UUID,
        task_id: UUID,
        expected_revision: int,
        event_id: UUID,
        update: WorkflowUpdate,
        request_digest: str | None = None,
    ) -> WorkflowTask: ...
    def event_result(
        self,
        owner: UUID,
        task_id: UUID,
        event_id: UUID,
        request_digest: str,
    ) -> WorkflowTask | None: ...
    def list(self, owner: UUID, workspace_id: UUID | None = None) -> tuple[WorkflowTask, ...]: ...
    def persistence_snapshot(self, owner: UUID) -> dict[str, object]: ...


class ControlRepository(Protocol):
    def guarded_write(self, owner: UUID, task_id: UUID, revision: int, write: Callable[[], None]) -> bool: ...
    def create(self, receipt: ControlReceipt, *, suspend_foreground: bool = False) -> ControlReceipt: ...
    def get(self, owner: UUID, task_id: UUID) -> ControlReceipt: ...
    def list(self, owner: UUID) -> tuple[ControlReceipt, ...]: ...
    def claim(
        self,
        owner: UUID,
        task_id: UUID,
        expected_revision: int,
        event_id: UUID,
        capability_id: str,
        mode: SaveMode,
    ) -> ControlReceipt: ...
    def revoke(
        self,
        owner: UUID,
        task_id: UUID,
        expected_revision: int,
        event_id: UUID | None = None,
    ) -> ControlReceipt: ...
    def finish(
        self,
        owner: UUID,
        task_id: UUID,
        expected_revision: int,
        event_id: UUID,
        *,
        status: str = "idle",
    ) -> ControlReceipt: ...
    def switch_mode(
        self,
        owner: UUID,
        task_id: UUID,
        expected_revision: int,
        event_id: UUID,
        mode: SaveMode,
    ) -> ControlReceipt: ...
    def recover(self, owner: UUID, task_id: UUID, expected_revision: int, event_id: UUID) -> ControlReceipt: ...


class WorkflowMessageInput(WorkflowDTO):
    text: str = Field(default="", max_length=2000)
    language: Literal["en", "zh"] = "en"
    client_turn_id: str = Field(default="turn-1", min_length=1, max_length=128)
    session_id: UUID | None = None
    conversation_id: UUID | None = None
    threaded: bool = False
    slots: dict[str, Any] = Field(default_factory=dict)
    navigation_context: NavigationInput | None = None
    photo_context: ChatPhotoContext | None = None
    medication_selection: MedicationSelection | None = None
    name_selection: NameSelection | None = None
    workspace_id: UUID | None = None
    task_id: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    ephemeral: EphemeralPayload | None = None
    save_mode: SaveMode = "allowed"


@dataclass(frozen=True)
class WorkflowMessageResult:
    reply: "AgentReply"
    conversation_id: UUID | None = None
    history_saved: bool | None = None
    workflow: WorkflowView | None = None
    explanations: tuple[ExplanationStep, ...] = ()


class ActionRepository(Protocol):
    def list(self, owner: UUID, task_id: UUID) -> tuple[ActionReceipt, ...]: ...
    def reserve(self, context: WorkflowContext, action_key: UUID) -> ActionReceipt: ...
    def complete(self, context: WorkflowContext, receipt: ActionReceipt) -> None: ...
    def read(self, owner: UUID, action_key: UUID) -> ActionReceipt: ...
