"""Current authority for independently confirmed native PDF library uploads."""

from collections.abc import Callable
from uuid import UUID

from ..contracts.assistant_workflows import WorkflowContext, validate_workflow_values
from ..contracts.library_files import LibraryFileDTO
from ..domain.errors import StaleVersionError
from .assistant_capabilities.pdf_upload import PdfUploadAdapter
from .assistant_workflows import WorkflowService
from .preferences import PreferenceService
from .workflow_media_upload_transactions import MediaUploadWorkflowTransactions


class WorkflowPdfUploadService:
    def __init__(self, *, workflows: WorkflowService, adapter: PdfUploadAdapter, preferences: PreferenceService,
                 transactions: MediaUploadWorkflowTransactions | None = None):
        self.workflows, self.adapter, self.preferences = workflows, adapter, preferences
        self.transactions = transactions

    def run(self, owner: UUID, task_id: UUID, revision: int, medication_id: UUID, data: bytes, filename: str,
            category: str, description: str, confirmed: bool,
            write: Callable[[], tuple[LibraryFileDTO, bool]]) -> tuple[LibraryFileDTO, bool]:
        if self.transactions is not None:
            return self.transactions.upload_pdf(owner, task_id, revision, medication_id, data, filename,
                                                 category, description, confirmed)
        view = self.workflows.view(owner, task_id)
        if (view.capability_id != "library.pdf.add" or view.result_ref is None
                or view.result_ref.kind != "media_review"):
            raise StaleVersionError("Reopen the independent PDF upload review")
        fields = validate_workflow_values(view.capability_id, view.input_fields or {})
        prefs = self.preferences.get(owner)
        context = WorkflowContext(owner=owner, task_id=task_id, revision=revision, capability_id=view.capability_id,
                                  language=prefs.preferred_language, timezone=prefs.timezone, save_mode=view.save_mode)
        ref = view.result_ref
        return self.workflows.guarded_patient_action(
            owner, task_id, revision, capability_id=view.capability_id, target_id=ref.id, target_kind="media_review",
            write=lambda: self.adapter.run_upload(context, fields, ref, medication_id, data, filename,
                                                  category, description, confirmed, write),
        )
