"""Versioned HTTP DTOs; no transport dependency in application messages."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from ..contracts.assistant_capabilities import CapabilityView
from ..contracts.assistant_explanations import ExplanationStep
from ..contracts.assistant_workflows import EphemeralPayload, SaveMode, WorkflowDTO, WorkflowEvent, WorkflowView
from ..contracts.workflow_attachments import AttachmentView
from ..contracts.workflow_runtime import WorkflowAdmission
from .schemas import AgentMessageRequest, AgentMessageResponse, Request


class WorkflowCapabilitiesResponse(WorkflowDTO):
    admission: WorkflowAdmission = Field(default_factory=WorkflowAdmission)
    contract_version: Literal[1] = 1
    enabled: bool
    progress_enabled: bool = False
    capabilities: tuple[CapabilityView, ...]


class StartWorkflowRequest(Request):
    capability_id: str = Field(max_length=120)
    workspace_id: UUID
    conversation_id: UUID | None = None
    values: dict[str, object] = Field(default_factory=dict)
    save_mode: SaveMode = "allowed"
    client_event_id: UUID


class WorkflowEventRequest(WorkflowEvent):
    ephemeral: EphemeralPayload | None = None


class WorkflowMessageRequest(AgentMessageRequest):
    workspace_id: UUID
    task_id: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    ephemeral: EphemeralPayload | None = None
    save_mode: SaveMode = "allowed"


class WorkflowMessageResponse(WorkflowDTO):
    reply: AgentMessageResponse
    workflow: WorkflowView | None
    explanations: tuple[ExplanationStep, ...] = ()


class WorkflowStreamRequest(WorkflowMessageRequest):
    run_id: UUID


class AttachmentUploadResponse(WorkflowDTO):
    attachment: AttachmentView
    workflow: WorkflowView


class RecoverOriginalRequest(Request):
    expected_revision: int = Field(ge=1)
    event_id: UUID


class ResumeDraftRequest(Request):
    expected_revision: int = Field(strict=True, ge=1)


class CleanupRetryRequest(Request):
    pass


class EphemeralPreviewRequest(Request):
    ephemeral: EphemeralPayload
