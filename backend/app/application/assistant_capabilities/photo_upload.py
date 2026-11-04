"""Prepare a gallery upload; only the independent patient API can materialize it."""

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
from ...contracts.media_workflow import PhotoUploadFields
from ...contracts.medication_evidence import GalleryUploadResult
from ...contracts.medication_management import ClinicalMutationGuard
from ...domain.errors import NotFoundError, StaleVersionError, ValidationError
from ..enrollment import MedicationEnrollmentService
from ..personal_gallery import PersonalGalleryService
from ..workflow_attachments import WorkflowAttachmentService


class PhotoUploadAdapter:
    capability_ids = frozenset({"gallery.photo.add"})

    def __init__(self, *, enrollment: MedicationEnrollmentService, gallery: PersonalGalleryService,
                 attachments: WorkflowAttachmentService, actions: ActionRepository, clinical: ClinicalMutationGuard):
        self.enrollment, self.gallery, self.attachments = enrollment, gallery, attachments
        self.actions, self.clinical = actions, clinical

    @staticmethod
    def _bound(context, row, ref=None):
        if (row.owner != context.owner or row.task_id != context.task_id or row.capability_id != context.capability_id
                or row.binding_revision > context.revision or ref is not None and row.business_ref != ref):
            raise StaleVersionError("The photo upload review belongs to another task or revision")

    def _original(self, context, values, assets):
        selected = values.source_attachment_id
        if selected is None and len(assets) == 1:
            selected = assets[0].id
        if selected is None:
            return None
        if selected not in {row.id for row in assets}:
            raise NotFoundError("Original not found in this patient task")
        return self.attachments.reference_original(context.owner, context.task_id, selected)

    def _draft(self, context, values, assets):
        if not isinstance(values, PhotoUploadFields):
            raise ValidationError("Use the typed photo upload draft")
        med = self.enrollment.get_medication(context.owner, values.medication_id) if values.medication_id else None
        if values.medication_id and med is None:
            raise NotFoundError("Medication not found for this patient")
        original = self._original(context, values, assets) if context.save_mode == "allowed" else None
        missing = tuple(name for name in ("medication_id", "image_kind", "source_description")
                        if getattr(values, name) is None)
        if original is None:
            missing += ("source_image",)
        return med, original, missing

    def _attempt(self, context, ref):
        try:
            receipt = self.actions.read(context.owner, uuid5(ref.id, "photo-patient-confirmation"))
        except NotFoundError:
            return None
        self._bound(context, receipt, ref)
        return receipt

    def _success(self, context, ref):
        for row in self.actions.list(context.owner, context.task_id):
            if (row.state == "succeeded" and row.safe_reason in {"photo_uploaded", "photo_duplicate"}
                    and row.action_key == uuid5(ref.id, f"photo-upload-result:{row.binding_revision}")):
                self._bound(context, row)
                return row
        return None

    def _review_ref(self, context, result_ref):
        if result_ref.kind == "media_review":
            self._bound(context, self.actions.read(context.owner, result_ref.id), result_ref)
            return result_ref
        for row in self.actions.list(context.owner, context.task_id):
            if row.safe_reason != "photo_upload_prepared" or row.business_ref is None:
                continue
            self._bound(context, row, row.business_ref)
            receipt = self._success(context, row.business_ref)
            if receipt and receipt.business_ref == result_ref:
                return row.business_ref
        raise NotFoundError("The owned photo upload receipt is unavailable")

    def _actual(self, context, values, ref):
        receipt = self._success(context, ref)
        if receipt is None or receipt.business_ref is None:
            return None
        row = self.gallery.metadata(context.owner, receipt.business_ref.id, include_deleted=True)
        if (row.medication_id != values.medication_id or row.metadata_version != receipt.business_ref.version
                or row.deleted_at is not None or row.gallery_removed):
            raise StaleVersionError("The uploaded photo changed; check its current gallery record")
        return row, receipt.safe_reason == "photo_duplicate"

    @staticmethod
    def _visible(row):
        return row.model_dump(mode="json", include={"id", "medication_id", "image_kind", "source_description",
                                                   "metadata_version", "eligibility", "eligibility_reason"})

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
                raise ValidationError("Choose one patient photo upload")
            ref = self._review_ref(context, results[0])
            try:
                actual = self._actual(context, values, ref)
            except (NotFoundError, StaleVersionError):
                if results[0].kind == "file":
                    return Preparation(input_fields=inputs, result_ref=results[0], workflow_state="completed",
                                       prompt_key="assistant.media.historical", view_fields={"historical_result": True})
                return Preparation(input_fields=inputs, result_ref=ref, workflow_state="failed_recoverable",
                                   prompt_key="assistant.photo.changed")
            if actual:
                return Preparation(input_fields=inputs, result_ref=results[0],
                                   workflow_state="completed" if results[0].kind == "file" else "awaiting_confirmation",
                                   prompt_key="assistant.photo.completed" if results[0].kind == "file"
                                   else "assistant.photo.check_result",
                                   view_fields={**visible, "photo": self._visible(actual[0]), "duplicate": actual[1]})
            if missing:
                raise StaleVersionError("The reviewed photo original is no longer available")
            return Preparation(input_fields=inputs, result_ref=ref, workflow_state="awaiting_confirmation",
                               prompt_key="assistant.photo.review",
                               view_fields={**visible, "original_id": str(original.id),
                               "upload_attempted": self._attempt(context, ref) is not None},
                               actions=(ExistingReviewAction(component_key="existing_media_management", owned_ref=ref,
                                                             expected_version=1),))
        if med is None:
            meds = self.enrollment.list_medications(context.owner)
            pages = max(1, (len(meds) + 9) // 10)
            page = values.page if values.page < pages else 0
            return Preparation(input_fields=inputs, missing_fields=missing, prompt_key="assistant.photo.medication",
                               view_fields={"page": page, "page_count": pages},
                               actions=(ChoiceAction(action_id="photo.medication", options=tuple(
                                   ChoiceOption(value=str(row.id), label_key="assistant.media.select",
                                                label_text=row.display_name[:200])
                                   for row in meds[page * 10:(page + 1) * 10])),) if meds else ())
        return Preparation(input_fields=inputs, missing_fields=missing,
                           workflow_state="collecting" if missing else "ready_for_review",
                           prompt_key="assistant.photo.collect" if missing else "assistant.photo.ready",
                           view_fields=visible)

    def prepare_once(self, context: WorkflowContext, values: BaseModel, assets: tuple[AttachmentRef, ...],
                     action_key: UUID) -> BusinessRef:
        if context.save_mode != "allowed" or self._draft(context, values, assets)[2]:
            raise ValidationError("Save the original and complete the photo details before patient review")
        ref = BusinessRef(kind="media_review", id=action_key, version=1)
        receipt = self.actions.reserve(context, action_key)
        self.actions.complete(context, receipt.model_copy(update={"business_ref": ref,
                              "safe_reason": "photo_upload_prepared", "state": "succeeded"}))
        return ref

    def reconcile(self, context: WorkflowContext, action_key: UUID) -> BusinessRef | None:
        try:
            row = self.actions.read(context.owner, action_key)
        except NotFoundError:
            return None
        self._bound(context, row)
        if row.binding_revision != context.revision:
            raise StaleVersionError("This photo preparation belongs to an old revision")
        return row.business_ref

    def revise_inputs(self, context, result_ref):
        if self._attempt(context, result_ref):
            raise StaleVersionError("Check or retry the same photo upload before changing its reviewed inputs")
        return {}

    def read_patient_result(self, context, result_ref, values=None):
        if values is None:
            raise ValidationError("Photo result readback needs the current typed draft")
        ref = self._review_ref(context, result_ref)
        if result_ref.kind == "file":
            return result_ref
        actual = self._actual(context, values, ref)
        return self._success(context, ref).business_ref if actual else ref

    def observe(self, context, result_ref):
        return OperationResult(state="pending", business_ref=result_ref)

    def run_patient_action(self, context, result_ref, write):
        return self.clinical.run(context.owner, self.clinical.revision(context.owner), write)

    def run_upload(self, context, values, ref, medication_id, image, image_kind, description,
                   reviewed, comparison, consent, write):
        self._bound(context, self.actions.read(context.owner, ref.id), ref)
        assets = self.attachments.assets(context.owner, context.task_id)
        _, original, missing = self._draft(context, values, assets)
        if (missing or medication_id != values.medication_id or image_kind != values.image_kind
                or description != values.source_description or not reviewed or comparison or not consent):
            raise StaleVersionError("Confirm the exact medicine, original photo and reviewed upload details")
        content, _ = self.attachments.read(context.owner, context.task_id, original.id)
        if content != image:
            raise StaleVersionError("This upload differs from the saved original photo")
        actual = self._actual(context, values, ref)
        if actual:
            return GalleryUploadResult(photo=actual[0], duplicate=actual[1])
        if self._attempt(context, ref) is None:
            receipt = self.actions.reserve(context, uuid5(ref.id, "photo-patient-confirmation"))
            self.actions.complete(context, receipt.model_copy(update={"business_ref": ref,
                                  "safe_reason": "photo_patient_confirmed", "state": "succeeded"}))
        result = write()
        row = self.gallery.metadata(context.owner, result.photo.id, include_deleted=True)
        if row.medication_id != medication_id or row.deleted_at is not None or row.gallery_removed:
            raise ValidationError("This original matches a removed photo; choose another original")
        actual_ref = BusinessRef(kind="file", id=row.id, version=row.metadata_version)
        receipt = self.actions.reserve(context, uuid5(ref.id, f"photo-upload-result:{context.revision}"))
        self.actions.complete(context, receipt.model_copy(update={"business_ref": actual_ref,
                              "safe_reason": "photo_duplicate" if result.duplicate else "photo_uploaded",
                              "state": "succeeded"}))
        return result
