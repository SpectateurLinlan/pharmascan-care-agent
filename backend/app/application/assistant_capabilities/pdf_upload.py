"""Prepare a library upload; only the independent patient API can materialize it."""

from uuid import UUID, uuid5

from pydantic import BaseModel

from ...contracts.assistant_workflows import (
    ActionRepository,
    AttachmentRef,
    BusinessRef,
    ChoiceAction,
    ChoiceOption,
    ExistingReviewAction,
    OperationResult,
    Preparation,
    WorkflowContext,
)
from ...contracts.media_workflow import PdfUploadFields
from ...contracts.medication_management import ClinicalMutationGuard
from ...domain.errors import NotFoundError, StaleVersionError, ValidationError
from ..enrollment import MedicationEnrollmentService
from ..library_files import MedicationLibraryFileService
from ..workflow_attachments import WorkflowAttachmentService


class PdfUploadAdapter:
    capability_ids = frozenset({"library.pdf.add"})

    def __init__(self, *, enrollment: MedicationEnrollmentService, library: MedicationLibraryFileService,
                 attachments: WorkflowAttachmentService, actions: ActionRepository, clinical: ClinicalMutationGuard):
        self.enrollment, self.library, self.attachments = enrollment, library, attachments
        self.actions, self.clinical = actions, clinical

    @staticmethod
    def _bound(context, row, ref=None):
        if (row.owner != context.owner or row.task_id != context.task_id or row.capability_id != context.capability_id
                or row.binding_revision > context.revision or ref is not None and row.business_ref != ref):
            raise StaleVersionError("The pdf upload review belongs to another task or revision")

    def _original(self, context, values, assets):
        selected = values.source_attachment_id
        if selected is None and len(assets) == 1:
            selected = assets[0].id
        if selected is None:
            return None
        if selected not in {row.id for row in assets}:
            raise NotFoundError("Original not found in this patient task")
        return self.attachments.pdf_original(context.owner, context.task_id, selected)

    def _draft(self, context, values, assets):
        if not isinstance(values, PdfUploadFields):
            raise ValidationError("Use the typed pdf upload draft")
        med = self.enrollment.get_medication(context.owner, values.medication_id) if values.medication_id else None
        if values.medication_id and med is None:
            raise NotFoundError("Medication not found for this patient")
        original = self._original(context, values, assets) if context.save_mode == "allowed" else None
        missing = tuple(name for name in ("medication_id", "filename", "category")
                        if getattr(values, name) is None)
        if original is None:
            missing += ("source_pdf",)
        return med, original, missing

    def _attempt(self, context, ref):
        try:
            receipt = self.actions.read(context.owner, uuid5(ref.id, "pdf-patient-confirmation"))
        except NotFoundError:
            return None
        self._bound(context, receipt, ref)
        return receipt

    def _success(self, context, ref):
        for row in self.actions.list(context.owner, context.task_id):
            if (row.state == "succeeded" and row.safe_reason in {"pdf_uploaded", "pdf_duplicate"}
                    and row.action_key == uuid5(ref.id, f"pdf-upload-result:{row.binding_revision}")):
                self._bound(context, row)
                return row
        return None

    def _review_ref(self, context, result_ref):
        if result_ref.kind == "media_review":
            self._bound(context, self.actions.read(context.owner, result_ref.id), result_ref)
            return result_ref
        for row in self.actions.list(context.owner, context.task_id):
            if row.safe_reason != "pdf_upload_prepared" or row.business_ref is None:
                continue
            self._bound(context, row, row.business_ref)
            receipt = self._success(context, row.business_ref)
            if receipt and receipt.business_ref == result_ref:
                return row.business_ref
        raise NotFoundError("The owned pdf upload receipt is unavailable")

    def _actual(self, context, values, ref):
        receipt = self._success(context, ref)
        if receipt is None or receipt.business_ref is None:
            return None
        row = self.library.metadata(context.owner, receipt.business_ref.id, include_deleted=True)
        if (row.medication_id != values.medication_id or row.version != receipt.business_ref.version
                or row.deleted_at is not None):
            raise StaleVersionError("The uploaded pdf changed; check its current library record")
        return row, receipt.safe_reason == "pdf_duplicate"

    @staticmethod
    def _visible(row):
        return row.model_dump(mode="json", include={"id", "medication_id", "original_filename", "display_title",
                                                   "category", "description", "version", "byte_size"})

    def prepare(self, context: WorkflowContext, values: BaseModel, assets: tuple[AttachmentRef, ...],
                results: tuple[BusinessRef, ...] = ()) -> Preparation:
        med, original, missing = self._draft(context, values, assets)
        inputs = values.model_dump(mode="json", exclude_none=True)
        if context.save_mode == "ephemeral":
            inputs.pop("source_attachment_id", None)
        elif original:
            inputs["source_attachment_id"] = str(original.id)
        visible = {"medication_name": med.display_name} if med else {}
        visible["originals"] = [{"id": str(row.id)} for row in assets]
        if results and context.save_mode == "allowed":
            if len(results) != 1:
                raise ValidationError("Choose one patient pdf upload")
            ref = self._review_ref(context, results[0])
            try:
                actual = self._actual(context, values, ref)
            except (NotFoundError, StaleVersionError):
                if results[0].kind == "file":
                    return Preparation(input_fields=inputs, result_ref=results[0], workflow_state="completed",
                                       prompt_key="assistant.media.historical", view_fields={"historical_result": True})
                return Preparation(input_fields=inputs, result_ref=ref, workflow_state="failed_recoverable",
                                   prompt_key="assistant.pdf.changed")
            if actual:
                return Preparation(input_fields=inputs, result_ref=results[0],
                                   workflow_state="completed" if results[0].kind == "file" else "awaiting_confirmation",
                                   prompt_key="assistant.pdf.completed" if results[0].kind == "file"
                                   else "assistant.pdf.check_result",
                                   view_fields={**visible, "file": self._visible(actual[0]), "duplicate": actual[1]})
            if missing:
                raise StaleVersionError("The reviewed pdf original is no longer available")
            return Preparation(input_fields=inputs, result_ref=ref, workflow_state="awaiting_confirmation",
                               prompt_key="assistant.pdf.review",
                               view_fields={**visible, "original_id": str(original.id),
                               "upload_attempted": self._attempt(context, ref) is not None},
                               actions=(ExistingReviewAction(component_key="existing_media_management", owned_ref=ref,
                                                             expected_version=1),))
        if med is None:
            meds = self.enrollment.list_medications(context.owner)
            pages = max(1, (len(meds) + 9) // 10)
            page = values.page if values.page < pages else 0
            return Preparation(input_fields=inputs, missing_fields=missing, prompt_key="assistant.pdf.medication",
                               view_fields={"page": page, "page_count": pages},
                               actions=(ChoiceAction(action_id="pdf.medication", options=tuple(
                                   ChoiceOption(value=str(row.id), label_key="assistant.media.select",
                                                label_text=row.display_name[:200])
                                   for row in meds[page * 10:(page + 1) * 10])),) if meds else ())
        return Preparation(input_fields=inputs, missing_fields=missing,
                           workflow_state="collecting" if missing else "ready_for_review",
                           prompt_key="assistant.pdf.collect" if missing else "assistant.pdf.ready",
                           view_fields=visible)

    def prepare_once(self, context: WorkflowContext, values: BaseModel, assets: tuple[AttachmentRef, ...],
                     action_key: UUID) -> BusinessRef:
        if context.save_mode != "allowed" or self._draft(context, values, assets)[2]:
            raise ValidationError("Save the original and complete the pdf details before patient review")
        ref = BusinessRef(kind="media_review", id=action_key, version=1)
        receipt = self.actions.reserve(context, action_key)
        self.actions.complete(context, receipt.model_copy(update={"business_ref": ref,
                              "safe_reason": "pdf_upload_prepared", "state": "succeeded"}))
        return ref

    def reconcile(self, context: WorkflowContext, action_key: UUID) -> BusinessRef | None:
        try:
            row = self.actions.read(context.owner, action_key)
        except NotFoundError:
            return None
        self._bound(context, row)
        if row.binding_revision != context.revision:
            raise StaleVersionError("This pdf preparation belongs to an old revision")
        return row.business_ref

    def revise_inputs(self, context, result_ref):
        if self._attempt(context, result_ref):
            raise StaleVersionError("Check or retry the same pdf upload before changing its reviewed inputs")
        return {}

    def read_patient_result(self, context, result_ref, values=None):
        if values is None:
            raise ValidationError("PDF result readback needs the current typed draft")
        ref = self._review_ref(context, result_ref)
        if result_ref.kind == "file":
            return result_ref
        actual = self._actual(context, values, ref)
        return self._success(context, ref).business_ref if actual else ref

    def observe(self, context, result_ref):
        return OperationResult(state="pending", business_ref=result_ref)

    def run_patient_action(self, context, result_ref, write):
        return self.clinical.run(context.owner, self.clinical.revision(context.owner), write)

    def run_upload(self, context, values, ref, medication_id, data, filename, category, description,
                   confirmed, write):
        self._bound(context, self.actions.read(context.owner, ref.id), ref)
        assets = self.attachments.assets(context.owner, context.task_id)
        _, original, missing = self._draft(context, values, assets)
        if (missing or medication_id != values.medication_id or filename != values.filename
                or category != values.category or description != values.description or not confirmed):
            raise StaleVersionError("Confirm the exact medication, original PDF and reviewed upload details")
        content, mime = self.attachments.read(context.owner, context.task_id, original.id)
        if mime != "application/pdf" or content != data:
            raise StaleVersionError("This upload differs from the saved original PDF")
        actual = self._actual(context, values, ref)
        if actual:
            return actual
        if self._attempt(context, ref) is None:
            receipt = self.actions.reserve(context, uuid5(ref.id, "pdf-patient-confirmation"))
            self.actions.complete(context, receipt.model_copy(update={"business_ref": ref,
                                  "safe_reason": "pdf_patient_confirmed", "state": "succeeded"}))
        result, duplicate = write()
        row = self.library.metadata(context.owner, result.id, include_deleted=True)
        if row.medication_id != medication_id or row.deleted_at is not None:
            raise ValidationError("This original matches a removed PDF; choose another original")
        actual_ref = BusinessRef(kind="file", id=row.id, version=row.version)
        receipt = self.actions.reserve(context, uuid5(ref.id, f"pdf-upload-result:{context.revision}"))
        self.actions.complete(context, receipt.model_copy(update={"business_ref": actual_ref,
                              "safe_reason": "pdf_duplicate" if duplicate else "pdf_uploaded",
                              "state": "succeeded"}))
        return result, duplicate
