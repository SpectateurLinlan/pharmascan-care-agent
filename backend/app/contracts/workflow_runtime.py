"""Explicit request-local ports. Component construction is not rollout readiness."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .assistant_capabilities import CapabilityMode
from .assistant_workflows import ActionRepository, ControlRepository, WorkflowRepository
from .native_media_verification import NativeMediaObserver
from .workflow_care_writes import CareWorkflowWritePort
from .workflow_coordination import BusinessReceiptReader
from .workflow_media_cleanup import MediaCleanupTicketPort, MediaDeleteVerificationPort
from .workflow_media_storage import MediaCopyTicketPort, MediaCopyVerificationPort
from .workflow_media_writes import MediaWorkflowWritePort
from .workflow_medication_writes import MedicationWorkflowWritePort
from .workflow_messages import ConversationPersistencePort
from .workflow_persistence import WorkflowMutationPort
from .workflow_record_writes import RecordWorkflowWritePort
from .workflow_reminder_writes import ReminderWorkflowWritePort
from .workflow_run_control import DurableRunControlPort, RunControlState, RunWorkerCommand
from .workflow_settings_writes import SettingsWorkflowWritePort
from .workflow_verification import EvidenceVerificationPort, VerifiedOriginalPort

RUNTIME_RELEASE_CONTRACT = "assistant-persistence-v1"


class RuntimeReleaseSnapshot(BaseModel):
    """Technical release metadata, never patient identity or clinical authority."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    contract_version: str = Field(min_length=1, max_length=80)
    accepted: bool = False
    release_id: UUID | None = None
    application_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    catalog_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    native_media_ready: bool = False

    @model_validator(mode="after")
    def accepted_release_is_complete(self):
        if self.accepted and any(
            value is None
            for value in (
                self.release_id,
                self.application_hash,
                self.catalog_digest,
            )
        ):
            raise ValueError("Accepted release metadata is incomplete")
        return self


class RuntimeReadinessPort(Protocol):
    def read_release(self, *, timeout_seconds: float) -> RuntimeReleaseSnapshot: ...


class WorkflowAdmission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    available: bool = False
    reason: Literal[
        "not_checked",
        "feature_disabled",
        "ready",
        "release_not_accepted",
        "release_contract_mismatch",
        "release_target_mismatch",
        "application_mismatch",
        "application_unidentified",
        "native_media_not_ready",
        "verification_unavailable",
        "readiness_unavailable",
        "incomplete_capabilities",
    ] = "not_checked"


def unavailable_admission(reason: str) -> WorkflowAdmission:
    """Unknown exception/provider text cannot become a public reason."""
    known = WorkflowAdmission.model_fields["reason"].annotation.__args__
    return WorkflowAdmission(reason=reason if reason in known and reason != "ready" else "readiness_unavailable")


class WorkflowTechnicalVerifier(
    EvidenceVerificationPort,
    MediaCopyVerificationPort,
    MediaDeleteVerificationPort,
    NativeMediaObserver,
    RuntimeReadinessPort,
    Protocol,
):
    def record_run(self, command: RunWorkerCommand, *, timeout_seconds: float) -> RunControlState: ...


@dataclass(frozen=True)
class CapabilityPersistenceBoundary:
    capability_id: str
    mode: CapabilityMode
    family: Literal[
        "medications",
        "records",
        "care",
        "media",
        "settings",
        "reminders",
        "messages",
        "workflow",
        "native_read",
        "device",
        "auth",
        "navigation",
    ]
    patient_ports: frozenset[str]
    confirmation: Literal["independent_patient_api", "workflow_control", "read_only", "browser"]
    external_boundary: Literal["verified_private_storage", "provider_read", "browser_handoff"] | None = None


@dataclass(frozen=True, repr=False)
class PersistentWorkflowPorts:
    boundaries: Mapping[str, CapabilityPersistenceBoundary]
    tasks: WorkflowRepository
    controls: ControlRepository
    actions: ActionRepository
    mutations: WorkflowMutationPort
    receipts: BusinessReceiptReader
    messages: ConversationPersistencePort
    runs: DurableRunControlPort
    originals: VerifiedOriginalPort
    media_copies: MediaCopyTicketPort
    media_cleanup: MediaCleanupTicketPort
    medications: MedicationWorkflowWritePort
    records: RecordWorkflowWritePort
    care: CareWorkflowWritePort
    media: MediaWorkflowWritePort
    settings: SettingsWorkflowWritePort
    reminders: ReminderWorkflowWritePort
    verifier: WorkflowTechnicalVerifier | None = field(repr=False)
    verification_reason: Literal["verification_unavailable"] | None = None
    # Native caller conversion and isolated SQL/role acceptance are separate.
    # Merely having a DSN/flag/recording test can never enable the runtime.
    rollout_ready: Literal[False] = False

    def __repr__(self):
        return "PersistentWorkflowPorts(request_scoped=True, rollout_ready=False)"
