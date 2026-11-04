"""Media review receipts never grant the model authority to perform patient writes."""

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID, uuid5

from pydantic import BaseModel

from ...contracts.assistant_workflows import (
    ActionRepository,
    AttachmentRef,
    BusinessRef,
    ExistingReviewAction,
    OperationResult,
    Preparation,
    WorkflowContext,
)
from ...contracts.media_workflow import MEDIA_CHANGE_SCHEMAS
from ...contracts.medication_management import ClinicalMutationGuard
from ...domain.errors import NotFoundError, StaleVersionError, ValidationError
from ..enrollment import MedicationEnrollmentService
from ..library_files import MedicationLibraryFileService
from ..personal_gallery import PersonalGalleryService
from .media_drafts import MediaDrafts

T = TypeVar("T")


class MediaMutationAdapter:
    def __init__(self, *, enrollment: MedicationEnrollmentService, gallery: PersonalGalleryService | None,
                 library: MedicationLibraryFileService | None, actions: ActionRepository,
                 clinical: ClinicalMutationGuard):
        self.drafts = MediaDrafts(enrollment=enrollment, gallery=gallery, library=library)
        self.actions, self.clinical = actions, clinical
        self.capability_ids = frozenset(name for name in MEDIA_CHANGE_SCHEMAS
                                       if (gallery is not None and (library is not None or name.endswith("retire"))
                                           if name.startswith("gallery.") else library is not None))
        self.write_ids = self.capability_ids

    @staticmethod
    def _bound(context, receipt, ref=None):
        if (receipt.owner != context.owner or receipt.task_id != context.task_id
                or receipt.capability_id != context.capability_id or receipt.binding_revision > context.revision
                or ref is not None and receipt.business_ref != ref):
            raise StaleVersionError("This media review belongs to another task or revision")

    def _receipt(self, context, ref, name):
        try:
            row = self.actions.read(context.owner, uuid5(ref.id, name))
        except NotFoundError:
            return None
        self._bound(context, row)
        return row

    def _snapshot(self, context, values):
        # Native media metadata already has an owned CAS version. Recheck that
        # version and protection policy without retaining another content hash.
        target = self.drafts.target(context, values)
        self.drafts.validate_target_action(context, target)
        return "media_prepared"

    def _current(self, context, values):
        return self.drafts.target(context, values, current_version=False, include_deleted=True)

    def _effect_matches(self, context, values, row):
        capability = context.capability_id
        if capability.endswith("delete"):
            return row.deleted_at is not None and not row.cleanup_pending
        if row.deleted_at is not None:
            return False
        if capability == "gallery.photo.remove":
            return row.gallery_removed
        if capability == "gallery.photo.retire":
            return row.eligibility == "ineligible" and row.eligibility_reason == "patient_retired_reference"
        payload = self.drafts.payload(context, values)
        if capability == "gallery.photo.edit":
            return row.image_kind == payload["image_kind"] and row.source_description == payload["source_description"]
        return (row.display_title == payload["title"] and row.category == payload["category"]
                and row.description == payload["description"])

    def _actual(self, context, values, ref):
        receipt = self._receipt(context, ref, "media-native-success")
        if receipt is None or receipt.safe_reason != "media_saved" or receipt.state != "succeeded":
            return None
        row = self._current(context, values)
        actual_ref = BusinessRef(kind="file", id=row.id, version=self.drafts.version(row))
        if receipt.business_ref != actual_ref or not self._effect_matches(context, values, row):
            raise StaleVersionError("The actual media record changed after this patient action")
        return actual_ref, row

    def _partial_cleanup(self, context, values, ref):
        confirmation = self._receipt(context, ref, "media-patient-confirmation")
        if not context.capability_id.endswith("delete") or confirmation is None:
            return False
        self._bound(context, confirmation, ref)
        row = self._current(context, values)
        return (row.deleted_at is not None and row.cleanup_pending
                and self.drafts.version(row) == values.expected_version + 1)

    def _check_snapshot(self, context, values, ref):
        receipt = self.actions.read(context.owner, ref.id)
        self._bound(context, receipt, ref)
        if receipt.safe_reason != self._snapshot(context, values):
            raise StaleVersionError("The current file differs from the patient review")

    def _review_ref(self, context, values, ref):
        if ref.kind == "media_review":
            self._bound(context, self.actions.read(context.owner, ref.id), ref)
            return ref
        for receipt in self.actions.list(context.owner, context.task_id):
            candidate = receipt.business_ref
            if receipt.safe_reason != "media_prepared" or candidate is None:
                continue
            self._bound(context, receipt, candidate)
            actual = self._receipt(context, candidate, "media-native-success")
            if (actual and actual.state == "succeeded" and actual.safe_reason == "media_saved"
                    and actual.business_ref == ref):
                return candidate
        raise NotFoundError("The task-bound media result is unavailable")

    def prepare(self, context: WorkflowContext, values: BaseModel, assets: tuple[AttachmentRef, ...],
                results: tuple[BusinessRef, ...] = ()) -> Preparation:
        if assets or context.capability_id not in self.capability_ids:
            raise ValidationError("Use the selected typed media lifecycle workflow")
        inputs = values.model_dump(mode="json", exclude_none=True)
        if not results:
            try:
                return self.drafts.collect(context, values)
            except StaleVersionError:
                # Keep the original selected version and entered fields until
                # the patient explicitly chooses a current owned file again.
                target_field = "image_id" if context.capability_id.startswith("gallery.") else "file_id"
                reset = values.model_copy(update={target_field: None,
                                                  "expected_version": None, "page": 0})
                try:
                    choices = self.drafts.collect(context, reset)
                except NotFoundError:
                    choices = Preparation()
                return choices.model_copy(update={"input_fields": inputs,
                    "workflow_state": "failed_recoverable", "prompt_key": "assistant.media.changed"})
        if len(results) != 1:
            raise ValidationError("Choose one media review")
        ref = self._review_ref(context, values, results[0])
        try:
            actual = self._actual(context, values, ref)
            if actual:
                return Preparation(input_fields=inputs, result_ref=results[0],
                                   workflow_state="completed" if results[0].kind == "file" else "awaiting_confirmation",
                                   prompt_key="assistant.media.completed" if results[0].kind == "file"
                                   else "assistant.media.check_result",
                                   view_fields={"saved_record": self.drafts.visible(actual[1])})
            partial = self._partial_cleanup(context, values, ref)
            if not partial:
                self._check_snapshot(context, values, ref)
            review = self.drafts.review(context, values, partial_cleanup=partial)
        except (NotFoundError, StaleVersionError, ValidationError):
            if results[0].kind == "file":
                # The owned success receipt proves this earlier operation, not
                # the file's current content/version. Preserve the old ref.
                return Preparation(input_fields=inputs, result_ref=results[0], workflow_state="completed",
                                   prompt_key="assistant.media.historical", view_fields={"historical_result": True})
            return Preparation(input_fields=inputs, result_ref=ref, workflow_state="failed_recoverable",
                               prompt_key="assistant.media.changed")
        return Preparation(input_fields=inputs, result_ref=ref, workflow_state="awaiting_confirmation",
                           prompt_key="assistant.media.patient_review", view_fields={"media_review": review},
                           actions=(ExistingReviewAction(component_key="existing_media_management", owned_ref=ref,
                                                         expected_version=1),))

    def prepare_once(self, context: WorkflowContext, values: BaseModel, assets: tuple[AttachmentRef, ...],
                     action_key: UUID) -> BusinessRef:
        if context.save_mode != "allowed" or assets or self.drafts.collect(context, values).missing_fields:
            raise ValidationError("Save and complete this draft before preparing a patient media review")
        self.drafts.review(context, values)
        ref = BusinessRef(kind="media_review", id=action_key, version=1)
        receipt = self.actions.reserve(context, action_key)
        self.actions.complete(context, receipt.model_copy(update={
            "business_ref": ref, "safe_reason": self._snapshot(context, values), "state": "succeeded",
        }))
        return ref

    def reconcile(self, context: WorkflowContext, action_key: UUID) -> BusinessRef | None:
        try:
            receipt = self.actions.read(context.owner, action_key)
        except NotFoundError:
            return None
        self._bound(context, receipt)
        if receipt.binding_revision != context.revision:
            raise StaleVersionError("This media preparation belongs to an old revision")
        return receipt.business_ref

    def revise_inputs(self, context: WorkflowContext, result_ref: BusinessRef) -> dict:
        if self._receipt(context, result_ref, "media-patient-confirmation"):
            checked = self._receipt(context, result_ref, f"media-no-result:{context.revision - 1}")
            if checked is None or checked.safe_reason != "media_no_result_checked":
                raise StaleVersionError("Check the attempted media action before editing this review")
        return {}

    def read_patient_result(self, context: WorkflowContext, result_ref: BusinessRef,
                            values: BaseModel | None = None) -> BusinessRef:
        if values is None:
            raise ValidationError("Media result readback needs the current typed draft")
        ref = self._review_ref(context, values, result_ref)
        if result_ref.kind == "file":
            return result_ref
        actual = self._actual(context, values, ref)
        if actual:
            return actual[0]
        try:
            self._check_snapshot(context, values, ref)
        except (NotFoundError, StaleVersionError):
            return ref  # A changed/missing target never proves that the attempted write succeeded.
        check = self.actions.reserve(context, uuid5(ref.id, f"media-no-result:{context.revision}"))
        self.actions.complete(context, check.model_copy(update={
            "business_ref": ref, "safe_reason": "media_no_result_checked", "state": "succeeded",
        }))
        return ref

    def observe(self, context: WorkflowContext, result_ref: BusinessRef) -> OperationResult:
        return OperationResult(state="pending", business_ref=result_ref)

    def run_patient_action(self, context: WorkflowContext, result_ref: BusinessRef, write: Callable[[], T]) -> T:
        return self.clinical.run(context.owner, self.clinical.revision(context.owner), write)

    def run_bound_request(self, context, values, ref, target, payload, confirmed, write):
        self._bound(context, self.actions.read(context.owner, ref.id), ref)
        expected_target = values.image_id if self.drafts.photo(context.capability_id) else values.file_id
        if target != expected_target or payload != self.drafts.payload(context, values) or not confirmed:
            raise StaleVersionError("Confirm the exact patient media target and reviewed fields")
        actual = self._actual(context, values, ref)
        if actual:
            return {"deleted": True} if context.capability_id == "library.pdf.delete" else actual[1]
        partial = self._partial_cleanup(context, values, ref)
        if not partial:
            self._check_snapshot(context, values, ref)
        confirmation = self._receipt(context, ref, "media-patient-confirmation")
        if confirmation is None:
            confirmation = self.actions.reserve(context, uuid5(ref.id, "media-patient-confirmation"))
            self.actions.complete(context, confirmation.model_copy(update={
                "business_ref": ref, "safe_reason": "media_patient_confirmed", "state": "succeeded",
            }))
        else:
            self._bound(context, confirmation, ref)
        result = write()
        row = self._current(context, values)
        if not self._effect_matches(context, values, row):
            raise StaleVersionError("The native media result differs from the independently confirmed action")
        actual_ref = BusinessRef(kind="file", id=row.id, version=self.drafts.version(row))
        receipt = self.actions.reserve(context, uuid5(ref.id, "media-native-success"))
        self.actions.complete(context, receipt.model_copy(update={
            "business_ref": actual_ref, "safe_reason": "media_saved", "state": "succeeded",
        }))
        return result
