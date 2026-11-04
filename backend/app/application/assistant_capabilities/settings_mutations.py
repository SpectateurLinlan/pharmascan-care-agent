"""Shared current-review protocol for nonsecret native settings/contact operations."""

from collections.abc import Callable, Mapping
from typing import Protocol
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
from ...contracts.medication_management import ClinicalMutationGuard
from ...domain.errors import NotFoundError, StaleVersionError, ValidationError


class NativeDrafts(Protocol):
    """Explicit nonclinical patient-operation port; no repositories or arbitrary executors."""
    schemas: Mapping[str, type[BaseModel]]
    read_ids: frozenset[str]
    prompt: str
    review_component: str

    def collect(self, context: WorkflowContext, values: BaseModel) -> Preparation: ...
    def current(self, context: WorkflowContext, values: BaseModel, review_id: UUID | None = None): ...
    def payload(self, context: WorkflowContext, values: BaseModel, review_id: UUID): ...
    def check(self, context: WorkflowContext, values: BaseModel, review_id: UUID | None = None): ...
    def unchanged(self, context: WorkflowContext, values: BaseModel, review_id: UUID | None = None) -> bool: ...
    def target(self, context: WorkflowContext, values: BaseModel, review_id: UUID) -> UUID | None: ...
    def visible(self, context: WorkflowContext, values: BaseModel, review_id: UUID): ...
    def native_result(self, context: WorkflowContext, values: BaseModel, review_id: UUID): ...
    def verify(self, context: WorkflowContext, values: BaseModel, review_id: UUID, result: object) -> bool: ...


class SettingsMutationAdapter:
    def __init__(self, *, drafts: NativeDrafts, actions: ActionRepository,
                 clinical: ClinicalMutationGuard):
        self.drafts, self.actions, self.clinical = drafts, actions, clinical
        self.capability_ids = frozenset(drafts.schemas)
        self.write_ids = self.capability_ids - drafts.read_ids
        self.prompt = drafts.prompt

    def receipt(self, context, ref, suffix=None):
        try:
            row = self.actions.read(context.owner, uuid5(ref.id, suffix) if suffix else ref.id)
        except NotFoundError:
            if suffix:
                return None
            raise
        if (row.task_id != context.task_id or row.owner != context.owner or row.capability_id != context.capability_id
                or row.binding_revision > context.revision):
            raise StaleVersionError("This settings review belongs to another task")
        return row

    def review_ref(self, context, ref):
        if ref.kind == "settings_review" and self.receipt(context, ref).business_ref == ref:
            return ref
        for row in self.actions.list(context.owner, context.task_id):
            candidate = row.business_ref
            if candidate and candidate.kind == "settings_review":
                success = self.receipt(context, candidate, "settings-native-success")
                if success and success.state == "succeeded" and success.business_ref == ref:
                    return candidate
        raise NotFoundError("The task has no actual settings success receipt")

    def check(self, context, values, ref):
        self.drafts.check(context, values, ref.id)
        if self.receipt(context, ref).clinical_revision != self.clinical.revision(context.owner):
            raise StaleVersionError("The clinical context changed; prepare a new settings review")

    def prepare(self, context: WorkflowContext, values: BaseModel, assets: tuple[AttachmentRef, ...],
                results: tuple[BusinessRef, ...] = ()) -> Preparation:
        if assets or context.capability_id not in self.capability_ids:
            raise ValidationError("Use the selected typed settings draft")
        if not results:
            return self.drafts.collect(context, values)
        if len(results) != 1 or context.capability_id not in self.write_ids:
            raise ValidationError("Choose one prepared settings review")
        ref = self.review_ref(context, results[0])
        inputs = values.model_dump(mode="json", exclude_none=True)
        visible = self.drafts.visible(context, values, ref.id)
        success = self.receipt(context, ref, "settings-native-success")
        if success and success.state == "succeeded":
            return Preparation(input_fields=inputs, result_ref=results[0], view_fields=visible,
                workflow_state="completed" if results[0].kind == "settings_action" else "awaiting_confirmation",
                prompt_key=f"{self.prompt}.saved" if results[0].kind == "settings_action"
                else f"{self.prompt}.check_result")
        try:
            self.check(context, values, ref)
        except (NotFoundError, StaleVersionError, ValidationError):
            return Preparation(input_fields=inputs, result_ref=ref, view_fields=visible,
                workflow_state="failed_recoverable", prompt_key=f"{self.prompt}.changed")
        return Preparation(input_fields=inputs, result_ref=ref, workflow_state="awaiting_confirmation",
            prompt_key=f"{self.prompt}.patient_review", view_fields={**visible, "settings_review": {
                "target_id": str(self.drafts.target(context, values, ref.id))
                    if self.drafts.target(context, values, ref.id) else None,
                "payload": self.drafts.payload(context, values, ref.id)}}, actions=(ExistingReviewAction(
                    component_key=self.drafts.review_component, owned_ref=ref, expected_version=1),))

    def prepare_once(self, context, values, assets, action_key):
        if context.save_mode != "allowed" or assets or context.capability_id not in self.write_ids:
            raise ValidationError("Save and complete the draft before independent patient review")
        self.drafts.check(context, values, action_key)
        ref = BusinessRef(kind="settings_review", id=action_key, version=1)
        row = self.actions.reserve(context, action_key)
        self.actions.complete(context, row.model_copy(update={"business_ref": ref, "state": "succeeded",
            "clinical_revision": self.clinical.revision(context.owner), "safe_reason": "settings_prepared"}))
        return ref

    def reconcile(self, context, action_key):
        try:
            return self.receipt(context, BusinessRef(kind="settings_review", id=action_key)).business_ref
        except NotFoundError:
            return None

    def revise_inputs(self, context, result_ref):
        ref = self.review_ref(context, result_ref)
        if self.receipt(context, ref, "settings-native-success"):
            raise StaleVersionError("This settings change already succeeded")
        if self.receipt(context, ref, "settings-patient-confirmation"):
            checked = self.receipt(context, ref, f"settings-no-result:{context.revision - 1}")
            if checked is None or checked.safe_reason != "settings_no_result_checked":
                raise StaleVersionError("Check the actual settings result before editing")
        return {}

    def read_patient_result(self, context, result_ref, values=None):
        ref = self.review_ref(context, result_ref)
        success = self.receipt(context, ref, "settings-native-success")
        if success and success.state == "succeeded":
            self.drafts.current(context, values, ref.id)
            return success.business_ref
        if self.drafts.unchanged(context, values, ref.id):
            row = self.actions.reserve(context, uuid5(ref.id, f"settings-no-result:{context.revision}"))
            self.actions.complete(context, row.model_copy(update={"business_ref": ref,
                "state": "succeeded", "safe_reason": "settings_no_result_checked"}))
        return ref

    def observe(self, context, result_ref):
        return OperationResult(state="pending", business_ref=result_ref)

    def run_patient_action(self, context: WorkflowContext, result_ref: BusinessRef, write: Callable[[], object]):
        return self.clinical.run(context.owner, self.clinical.revision(context.owner), write)

    def run_bound_request(self, context, values, ref, target: UUID | None, payload: BaseModel | None, confirmed, write):
        self.validate_payload(context, values, ref, target, payload, confirmed)
        if self.receipt(context, ref, "settings-native-success"):
            return self.drafts.native_result(context, values, ref.id)
        self.check(context, values, ref)
        if self.receipt(context, ref, "settings-patient-confirmation"):
            raise StaleVersionError("Check the uncertain result instead of repeating this settings write")
        row = self.actions.reserve(context, uuid5(ref.id, "settings-patient-confirmation"))
        self.actions.complete(context, row.model_copy(update={"business_ref": ref,
            "state": "succeeded", "safe_reason": "settings_patient_confirmed"}))
        result = write()
        if not self.drafts.verify(context, values, ref.id, result):
            raise StaleVersionError("The actual native settings result could not be verified")
        row = self.actions.reserve(context, uuid5(ref.id, "settings-native-success"))
        actual_ref = BusinessRef(kind="settings_action", id=row.action_key, version=1)
        self.actions.complete(context, row.model_copy(update={"business_ref": actual_ref,
            "state": "succeeded", "safe_reason": "settings_saved"}))
        return result

    def review_snapshot(self, context, values, ref):
        """Public pure validation/projection for a separately owned transaction."""
        self.drafts.check(context, values, ref.id)
        return self.drafts.current(context, values, ref.id)

    def validate_payload(self, context, values, ref, target, payload, confirmed):
        expected = self.drafts.payload(context, values, ref.id)
        actual = payload.model_dump(mode="json", exclude_unset=not context.capability_id.startswith("caregiver.")) \
            if payload is not None else {}
        if not confirmed or target != self.drafts.target(context, values, ref.id) or expected != actual:
            raise StaleVersionError("Confirm the exact current patient settings target and fields")
