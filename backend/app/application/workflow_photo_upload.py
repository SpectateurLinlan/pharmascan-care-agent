"""Current task authority for the existing independently confirmed gallery upload API."""

from collections.abc import Callable
from uuid import UUID

from ..contracts.assistant_workflows import WorkflowContext, validate_workflow_values
from ..contracts.medication_evidence import GalleryUploadResult, ImageKind
from ..domain.errors import StaleVersionError
from .assistant_capabilities.photo_upload import PhotoUploadAdapter
from .assistant_workflows import WorkflowService
from .preferences import PreferenceService
from .workflow_media_upload_transactions import MediaUploadWorkflowTransactions


class WorkflowPhotoUploadService:
    def __init__(self, *, workflows: WorkflowService, adapter: PhotoUploadAdapter, preferences: PreferenceService,
                 transactions: MediaUploadWorkflowTransactions | None = None):
        self.workflows, self.adapter, self.preferences = workflows, adapter, preferences
        self.transactions = transactions

    def run(self, owner: UUID, task_id: UUID, revision: int, medication_id: UUID, image: bytes, image_kind: ImageKind,
            description: str, reviewed: bool, comparison: bool, consent: bool,
            write: Callable[[], GalleryUploadResult]) -> GalleryUploadResult:
        if self.transactions is not None:
            return self.transactions.upload_photo(owner, task_id, revision, medication_id, image, image_kind,
                                                   description, reviewed, comparison, consent)
        view = self.workflows.view(owner, task_id)
        if (view.capability_id != "gallery.photo.add" or view.result_ref is None
                or view.result_ref.kind != "media_review"):
            raise StaleVersionError("Reopen the independent photo upload review")
        fields = validate_workflow_values(view.capability_id, view.input_fields or {})
        prefs = self.preferences.get(owner)
        context = WorkflowContext(owner=owner, task_id=task_id, revision=revision, capability_id=view.capability_id,
                                  language=prefs.preferred_language, timezone=prefs.timezone, save_mode=view.save_mode)
        ref = view.result_ref
        return self.workflows.guarded_patient_action(
            owner, task_id, revision, capability_id=view.capability_id, target_id=ref.id, target_kind="media_review",
            write=lambda: self.adapter.run_upload(context, fields, ref, medication_id, image, image_kind,
                                                   description, reviewed, comparison, consent, write),
        )
