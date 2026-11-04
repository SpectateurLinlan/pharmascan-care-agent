"""Explicit source evidence preview; no durable extraction or medication writes."""

from collections.abc import Callable
from uuid import UUID

from pydantic import ValidationError as SchemaValidationError

from ..contracts.medication_management import ClinicalMutationGuard
from ..contracts.source_extraction import MedicationSourceExtractionDTO
from ..contracts.source_preview_workflow import SourcePreviewFields, SourcePreviewQuery, SourcePreviewResult
from ..contracts.workflow_attachments import ImageMime
from ..domain.errors import ProviderUnavailableError, StaleVersionError, ValidationError
from .assistant_capabilities.source_preview import SourcePreviewAdapter
from .assistant_workflows import WorkflowService
from .source_preview import SourcePreviewService
from .workflow_attachments import WorkflowAttachmentService


class WorkflowSourcePreviewService:
    def __init__(self, *, workflows: WorkflowService, attachments: WorkflowAttachmentService,
                 preview: SourcePreviewService | None, normalize: Callable[[bytes], bytes],
                 clinical: ClinicalMutationGuard):
        self.workflows, self.attachments, self.preview = workflows, attachments, preview
        self.adapter, self.normalize = SourcePreviewAdapter(attachments=attachments), normalize
        self.clinical = clinical

    def query(self, owner: UUID, task_id: UUID, request: SourcePreviewQuery, image: bytes, mime: ImageMime,
              consent: bool) -> SourcePreviewResult:
        context, values = self.workflows.read_only_input(owner, task_id, request.expected_revision,
                                                        "source.preview", request.ephemeral)
        if not isinstance(values, SourcePreviewFields) or not consent:
            raise ValidationError("Explicitly allow source processing before previewing")
        if not 0 < len(image) <= 8_000_000 or not (
            mime == "image/png" and image.startswith(b"\x89PNG\r\n\x1a\n")
            or mime == "image/jpeg" and image.startswith(b"\xff\xd8\xff")
        ):
            raise ValidationError("Choose a PNG/JPEG photo matching its content type and size limit")
        self.normalize(image)
        original = None
        if context.save_mode == "allowed":
            original = self.adapter.original(context, values, self.attachments.assets(owner, task_id))
            if original is None:
                raise ValidationError("Save this preview's original before processing")
            data, stored_mime = self.attachments.read(owner, task_id, original.id)
            if data != image or mime != stored_mime:
                raise StaleVersionError("This image differs from the saved preview original")
        clinical_revision = self.clinical.revision(owner)
        result, outcome, reason = None, "success", None
        try:
            if self.preview is None:
                raise ProviderUnavailableError("Source preview is unavailable")
            result = MedicationSourceExtractionDTO.model_validate(self.preview.preview(
                content=image, source_kind=values.source_kind, consent=True, demo_only=False,
            ))
            if result.source_kind != values.source_kind or result.provider_source != "photo":
                raise ValidationError("The source preview did not match the selected image type")
        except ProviderUnavailableError:
            result, outcome, reason = None, "unavailable", "service_unavailable"
        except (ValidationError, SchemaValidationError):
            result, outcome, reason = None, "rejected", "extraction_rejected"
        current = self.workflows.read_only_input(owner, task_id, request.expected_revision,
                                                 "source.preview", request.ephemeral)
        if current != (context, values) or self.clinical.revision(owner) != clinical_revision:
            raise StaleVersionError("Source preview changed during processing; discard this result")
        if original is not None:
            self.attachments.preview_original(owner, task_id, original.id)
        return SourcePreviewResult(outcome=outcome, preview=result, reason=reason)
