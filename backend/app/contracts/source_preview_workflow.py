"""Read-only source preview never carries reviewed instructions or write authority."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from .assistant_workflows import EphemeralPayload, WorkflowDTO
from .source_extraction import MedicationSourceExtractionDTO
from .workflow_attachments import SourceKind


class SourcePreviewFields(WorkflowDTO):
    source_kind: SourceKind = "pharmacy_label"
    source_attachment_id: UUID | None = None


class SourcePreviewQuery(WorkflowDTO):
    expected_revision: int = Field(strict=True, ge=1)
    ephemeral: EphemeralPayload | None = None


class SourcePreviewResult(WorkflowDTO):
    outcome: Literal["success", "unavailable", "rejected"]
    preview: MedicationSourceExtractionDTO | None = None
    reason: Literal["service_unavailable", "extraction_rejected"] | None = None
