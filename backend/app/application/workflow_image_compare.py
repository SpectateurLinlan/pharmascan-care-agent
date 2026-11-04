"""Explicit consented processing; never saves visual results or clinical records."""

from collections.abc import Callable
from uuid import UUID

from ..contracts.image_comparison import CompareCandidate, CompareFields, CompareQuery, ComparisonResult
from ..contracts.medication_management import ClinicalMutationGuard
from ..contracts.workflow_attachments import ImageMime
from ..domain.errors import ProviderUnavailableError, StaleVersionError, ValidationError
from .assistant_capabilities.image_compare import ImageCompareAdapter
from .assistant_workflows import WorkflowService
from .enrollment import MedicationEnrollmentService
from .personal_gallery import PersonalGalleryService
from .visual_check import VisualCheckService
from .workflow_attachments import WorkflowAttachmentService


class WorkflowImageCompareService:
    def __init__(self, *, workflows: WorkflowService, attachments: WorkflowAttachmentService,
                 enrollment: MedicationEnrollmentService, gallery: PersonalGalleryService | None,
                 visual: VisualCheckService | None, normalize: Callable[[bytes], bytes],
                 clinical: ClinicalMutationGuard):
        self.workflows, self.attachments, self.gallery, self.visual = workflows, attachments, gallery, visual
        self.adapter, self.normalize = ImageCompareAdapter(enrollment=enrollment, attachments=attachments), normalize
        self.clinical = clinical

    def query(self, owner: UUID, task_id: UUID, request: CompareQuery, image: bytes, mime: ImageMime,
              consent: bool) -> ComparisonResult:
        context, values = self.workflows.read_only_input(owner, task_id, request.expected_revision,
                                                        "image.compare", request.ephemeral)
        if not isinstance(values, CompareFields) or not consent:
            raise ValidationError("Explicitly allow photo processing before checking")
        self.adapter.selected(owner, values)
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
                raise ValidationError("Save the original photo before processing this saved task")
            data, stored_mime = self.attachments.read(owner, task_id, original.id)
            if data != image or mime != stored_mime:
                raise StaleVersionError("This image differs from the current saved original")
        clinical_revision = self.clinical.revision(owner)
        candidates, name = (), None
        try:
            if values.intent == "identify":
                if self.visual is None:
                    raise ProviderUnavailableError("Catalogue photo processing is unavailable")
                result = self.visual.check(patient_id=owner, regimen_id=None, image=image,
                                           consent=True, demo_only=False, enrollment=self.adapter.enrollment)
                decision = result.decision
                reason = "image_unclear" if decision == "ambiguous" else "no_reviewed_reference"
                candidates = tuple(CompareCandidate(name=row.display_name.strip()[:200],
                                   strength=row.strength[:100] if row.strength else None)
                                   for row in result.candidates[:10] if row.display_name and row.display_name.strip())
            else:
                if self.gallery is None:
                    raise ProviderUnavailableError("Personal photo processing is unavailable")
                result = self.gallery.preview_check(patient_id=owner, regimen_id=values.regimen_id,
                                                    image=image, consent=True, demo_only=False)
                decision = result.decision
                reason = {"match": "visual_reference_only", "unknown": "no_reviewed_reference",
                          "ambiguous": "image_unclear", "conflict": "plan_conflict",
                          "missing_reference": "missing_reference", "unavailable": "service_unavailable"}[decision]
                name = self.adapter.selected(owner, values)
        except ProviderUnavailableError:
            decision, reason, candidates = "unavailable", "service_unavailable", ()
        current = self.workflows.read_only_input(owner, task_id, request.expected_revision,
                                                 "image.compare", request.ephemeral)
        if current != (context, values) or self.clinical.revision(owner) != clinical_revision:
            raise StaleVersionError("The photo check changed while processing; discard this result")
        if original is not None:
            self.attachments.comparison_original(owner, task_id, original.id)
        self.adapter.selected(owner, values)
        return ComparisonResult(intent=values.intent, decision=decision, reason_key=reason,
                                candidates=candidates, selected_medication=name)
