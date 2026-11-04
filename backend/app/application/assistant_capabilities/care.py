"""Care preparation never writes clinical records; patient APIs own confirmation."""

import hashlib
import json
from collections.abc import Callable
from datetime import timedelta
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
from ...contracts.care_workflow import CARE_READ_IDS, CARE_SCHEMAS
from ...contracts.medication_management import ClinicalMutationGuard
from ...contracts.observations import ObservationInput
from ...contracts.ports import Clock
from ...domain.errors import NotFoundError, StaleVersionError, ValidationError
from ..enrollment import MedicationEnrollmentService
from ..long_term import LongTermCareService
from ..observations import ObservationService
from .care_drafts import CareDrafts


class CareAdapter:
    capability_ids = frozenset(CARE_SCHEMAS)
    write_ids = capability_ids - CARE_READ_IDS

    def __init__(
        self,
        *,
        enrollment: MedicationEnrollmentService,
        observations: ObservationService,
        care: LongTermCareService,
        clock: Clock,
        actions: ActionRepository,
        clinical: ClinicalMutationGuard,
    ):
        self.drafts = CareDrafts(enrollment=enrollment, observations=observations, care=care, clock=clock)
        self.enrollment, self.observations, self.care, self.clock = enrollment, observations, care, clock
        self.actions, self.clinical = actions, clinical

    @staticmethod
    def _binding(context, receipt, ref, *, current=False):
        if (
            receipt.owner != context.owner
            or receipt.task_id != context.task_id
            or receipt.capability_id != context.capability_id
            or receipt.business_ref != ref
            or (
                receipt.binding_revision != context.revision if current else receipt.binding_revision > context.revision
            )
        ):
            raise StaleVersionError("This care confirmation belongs to another task or revision")

    def _confirmed(self, context, ref):
        try:
            receipt = self.actions.read(context.owner, uuid5(ref.id, "care-patient-confirmation"))
            self._binding(context, receipt, ref)
        except NotFoundError:
            return None
        return receipt if receipt.safe_reason in {"care_patient_confirmed", "care_deleted", "care_saved"} else None

    def _snapshot(self, context, values):
        if context.capability_id in {"observation.delete", "observation.edit"}:
            row = self.observations.get(context.owner, values.observation_id)
            value = row.model_dump(mode="json") if row else None
        elif context.capability_id == "inventory.count":
            value = [
                row.model_dump(mode="json")
                for row in self.care.inventory(context.owner, values.medication_id, context.timezone).transactions
            ]
        else:
            return "care_prepared"
        return "care_prepared:" + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def _current_snapshot(self, context, values, ref):
        receipt = self.actions.read(context.owner, ref.id)
        if receipt.safe_reason != self._snapshot(context, values):
            raise StaleVersionError("The current record changed; prepare a new patient care review")

    def _actual(self, context, values, ref, *, require_receipt=True):
        confirmation = self._confirmed(context, ref)
        if require_receipt and confirmation is None:
            return None
        capability = context.capability_id
        if capability == "observation.delete":
            if confirmation and confirmation.safe_reason == "care_deleted":
                return BusinessRef(kind="observation", id=values.observation_id), {"deleted": True}
            return None
        if capability in {"observation.add", "observation.edit"}:
            if capability == "observation.edit" and (confirmation is None or confirmation.safe_reason != "care_saved"):
                return None
            record = self.observations.get(
                context.owner, ref.id if capability == "observation.add" else values.observation_id
            )
            kind = "observation"
        elif capability == "inventory.count":
            stock = self.care.inventory(context.owner, values.medication_id, context.timezone)
            record = next((row for row in stock.transactions if row.id == ref.id), None)
            kind = "stock"
        elif capability == "barrier.add":
            record = next((row for row in self.care.barriers(context.owner) if row.id == ref.id), None)
            kind = "barrier"
        else:
            target = ref.id if capability == "followup.add" else values.task_id
            record = next((row for row in self.care.tasks(context.owner) if row.id == target), None)
            if record is None:
                return None
            entry = next((row for row in record.history if row.id == ref.id), None)
            if entry is None:
                return None
            version = 1 if capability == "followup.add" else values.expected_version + 1
            return BusinessRef(kind="care_task", id=target, version=version), entry.model_dump(mode="json")
        if record is None:
            return None
        expected = self.drafts.review(context, values, ref.id)["payload"]
        actual = record.model_dump(mode="json")
        if any(actual.get(key) != value for key, value in expected.items() if key != "confirmed"):
            raise StaleVersionError("The actual care record differs from this confirmed draft")
        return BusinessRef(kind=kind, id=record.id), actual

    def _saved_observation(self, context, values, ref):
        if context.capability_id not in {"observation.add", "observation.edit"}:
            return None
        confirmation = self._confirmed(context, ref)
        if confirmation is None or confirmation.safe_reason != "care_saved":
            return None
        target = ref.id if context.capability_id == "observation.add" else values.observation_id
        return BusinessRef(kind="observation", id=target)

    def _review_ref(self, context, values, ref):
        if ref.kind == "care_review":
            receipt = self.actions.read(context.owner, ref.id)
            self._binding(context, receipt, ref)
            return ref
        for receipt in self.actions.list(context.owner, context.task_id):
            candidate = receipt.business_ref
            if not (receipt.safe_reason or "").startswith("care_prepared") or candidate is None:
                continue
            self._binding(context, receipt, candidate)
            saved = self._saved_observation(context, values, candidate)
            if saved == ref:
                return candidate
            actual = self._actual(context, values, candidate)
            if actual and actual[0] == ref:
                return candidate
        raise NotFoundError("The actual task-bound care result is unavailable")

    def _page(self, values, rows, key):
        pages = max(1, (len(rows) + 9) // 10)
        page = values.page if values.page < pages else 0
        return {key: rows[page * 10 : page * 10 + 10], "page": page, "page_count": pages, "total": len(rows)}

    def prepare(
        self,
        context: WorkflowContext,
        values: BaseModel,
        assets: tuple[AttachmentRef, ...],
        results: tuple[BusinessRef, ...] = (),
    ) -> Preparation:
        if assets or context.capability_id not in self.capability_ids:
            raise ValidationError("Care drafts do not accept photos or executable results")
        inputs = values.model_dump(mode="json", exclude_none=True)
        capability = context.capability_id
        if results:
            if len(results) != 1:
                raise ValidationError("Choose one care review")
            review_ref = self._review_ref(context, values, results[0])
            saved = self._saved_observation(context, values, review_ref)
            if saved:
                current = self.observations.get(context.owner, saved.id)
                expected = ObservationInput(id=saved.id, **values.model_dump(exclude={"observation_id"})).model_dump(
                    mode="json", exclude={"confirmed"})
                actual_fields = current.model_dump(mode="json", exclude={"patient_id"}) if current else None
                if actual_fields is None or any(actual_fields.get(key) != value for key, value in expected.items()):
                    pending = results[0].kind == "care_review"
                    return Preparation(input_fields=inputs, result_ref=results[0],
                        workflow_state="awaiting_confirmation" if pending else "completed",
                        prompt_key="assistant.care.check_result" if pending else "assistant.care.historical",
                        view_fields={"historical_result": True, "record_available": current is not None,
                                     "current_record": actual_fields})
            actual = self._actual(context, values, review_ref)
            if actual:
                return Preparation(
                    input_fields=inputs,
                    workflow_state="awaiting_confirmation" if results[0].kind == "care_review" else "completed",
                    prompt_key="assistant.care.check_result"
                    if results[0].kind == "care_review"
                    else "assistant.care.completed",
                    result_ref=results[0],
                    view_fields={"saved_record": actual[1], "result_kind": actual[0].kind},
                )
            try:
                self._current_snapshot(context, values, review_ref)
                review = self.drafts.review(context, values, review_ref.id)
            except (NotFoundError, ValidationError, StaleVersionError):
                return Preparation(
                    input_fields=inputs,
                    workflow_state="failed_recoverable",
                    result_ref=review_ref,
                    prompt_key="assistant.care.changed",
                )
            view = {"care_review": review, "timezone": context.timezone}
            if capability == "inventory.count":
                view["target_name"] = self.enrollment.get_medication(context.owner, values.medication_id).display_name
            elif capability in {"observation.add", "observation.edit"} and values.medication_id:
                view["target_name"] = self.enrollment.get_medication(context.owner, values.medication_id).display_name
            elif capability == "barrier.add" and values.regimen_id:
                plan = self.enrollment.get_regimen(context.owner, values.regimen_id)
                medicine = self.enrollment.get_medication(context.owner, plan.patient_medication_id)
                view["target_name"] = medicine.display_name
            elif capability.startswith("followup.") and capability != "followup.add":
                view["target_name"] = self.drafts.task(context.owner, values.task_id).title
            if capability.startswith("followup."):
                proposed = review["payload"]
                if getattr(values, "clear_plan", False):
                    view["association_state"] = "removed"
                elif proposed.get("regimen_id"):
                    plan = self.enrollment.get_regimen(context.owner, UUID(proposed["regimen_id"]))
                    medicine = self.enrollment.get_medication(context.owner, plan.patient_medication_id)
                    view.update(association_state="linked",
                                association_label=f"{medicine.display_name} · v{plan.version_no}")
                elif proposed.get("medication_id"):
                    medicine = self.enrollment.get_medication(context.owner, UUID(proposed["medication_id"]))
                    view.update(association_state="linked", association_label=medicine.display_name)
                else:
                    view["association_state"] = "none" if capability == "followup.add" else "unchanged"
            if not capability.startswith("observation."):
                view["proposal"] = self.drafts.care_proposal(capability, review).model_dump(
                    mode="json", exclude_unset=True
                )
            if capability == "observation.delete":
                view["observation"] = self.observations.get(context.owner, values.observation_id).model_dump(
                    mode="json"
                )
            return Preparation(
                input_fields=inputs,
                workflow_state="awaiting_confirmation",
                result_ref=review_ref,
                prompt_key="assistant.care.patient_review",
                view_fields=view,
                actions=(
                    ExistingReviewAction(
                        component_key="existing_observation_review"
                        if capability.startswith("observation.")
                        else "existing_care_review",
                        owned_ref=review_ref,
                        expected_version=1,
                    ),
                ),
            )
        self.drafts.associations(context.owner, values)
        if capability in CARE_READ_IDS and not self.drafts.missing(context, values):
            if capability == "observation.list":
                rows = self.observations.list(
                    context.owner,
                    self.clock.now() - timedelta(days=values.days),
                    self.clock.now() + timedelta(minutes=5),
                )
                rows = [
                    row for row in rows if values.medication_id is None or row.medication_id == values.medication_id
                ]
                visible = self._page(values, [row.model_dump(mode="json") for row in reversed(rows)], "records")
            elif capability == "inventory.view":
                stock = self.care.inventory(context.owner, values.medication_id, context.timezone)
                visible = {
                    "medication_name": self.enrollment.get_medication(context.owner, values.medication_id).display_name,
                    "stock": stock.model_dump(mode="json"),
                    **self._page(
                        values, [row.model_dump(mode="json") for row in reversed(stock.transactions)], "records"
                    ),
                }
                visible["stock"]["transactions"] = visible["records"]
            else:
                rows = (
                    self.care.tasks(context.owner)
                    if capability == "followup.list"
                    else self.care.barriers(context.owner)
                )
                visible = self._page(values, [row.model_dump(mode="json") for row in rows], "records")
            return Preparation(
                input_fields=inputs,
                workflow_state="collecting",
                prompt_key="assistant.care.read",
                view_fields={**visible, "timezone": context.timezone, "days": values.days},
            )
        missing = self.drafts.missing(context, values)
        meds = self.enrollment.list_medications(context.owner)
        visible = {
            "medications": [{"id": str(row.id), "name": row.display_name} for row in meds[:50]],
            "regimens": [
                {"id": str(plan.id), "name": med.display_name, "version": plan.version_no}
                for med in meds[:50]
                for plan in self.enrollment.list_regimens(context.owner, med.id)
            ][:50],
            "timezone": context.timezone,
            "as_of": self.clock.now().isoformat(),
        }
        action = None
        if "medication_id" in missing:
            action = (
                ChoiceAction(
                    action_id="care.medication",
                    options=tuple(
                        ChoiceOption(
                            value=str(row.id),
                            label_key="assistant.medication.select",
                            label_text=row.display_name[:200],
                        )
                        for row in meds[:50]
                    ),
                )
                if meds
                else None
            )
        elif "observation_id" in missing:
            rows = self.observations.list(
                context.owner, self.clock.now() - timedelta(days=366), self.clock.now() + timedelta(minutes=5)
            )
            action = (
                ChoiceAction(
                    action_id="care.observation",
                    options=tuple(
                        ChoiceOption(
                            value=str(row.id), label_key="assistant.care.select", label_text=row.description[:200]
                        )
                        for row in rows[:50]
                    ),
                )
                if rows
                else None
            )
        elif "task_id" in missing:
            rows = [
                row
                for row in self.care.tasks(context.owner)
                if capability == "followup.edit" or row.status not in {"completed", "cancelled"}
            ]
            action = (
                ChoiceAction(
                    action_id="care.task",
                    options=tuple(
                        ChoiceOption(
                            value=f"{row.id}:{row.version}",
                            label_key="assistant.care.select",
                            label_text=row.title[:200],
                        )
                        for row in rows[:50]
                    ),
                )
                if rows
                else None
            )
        if not missing and capability in self.write_ids:
            try:
                self.drafts.review(context, values, UUID(int=0))
            except StaleVersionError:
                if not capability.startswith("followup."):
                    raise
                rows = self.care.tasks(context.owner)
                return Preparation(input_fields=inputs, workflow_state="failed_recoverable",
                    prompt_key="assistant.care.changed", missing_fields=("task_id",),
                    view_fields=visible, actions=(ChoiceAction(action_id="care.task", options=tuple(
                        ChoiceOption(value=f"{row.id}:{row.version}", label_key="assistant.care.select",
                                     label_text=row.title[:200]) for row in rows[:50])),))
        if getattr(values, "task_id", None):
            visible["target_task"] = self.drafts.task(context.owner, values.task_id).model_dump(mode="json")
        if getattr(values, "observation_id", None):
            observation = self.observations.get(context.owner, values.observation_id)
            if observation is None:
                raise NotFoundError("Health note not found for this patient")
            visible["observation"] = observation.model_dump(mode="json")
        return Preparation(
            input_fields=inputs,
            workflow_state="collecting" if missing else "ready_for_review",
            prompt_key="assistant.care.collect" if missing else "assistant.care.ready",
            missing_fields=missing,
            view_fields=visible,
            actions=(action,) if action else (),
        )

    def prepare_once(
        self, context: WorkflowContext, values: BaseModel, assets: tuple[AttachmentRef, ...], action_key: UUID
    ) -> BusinessRef:
        if context.save_mode != "allowed" or assets or self.drafts.missing(context, values):
            raise ValidationError("Enable saving and complete the care draft before patient review")
        self.drafts.review(context, values, action_key)
        ref = BusinessRef(kind="care_review", id=action_key, version=1)
        receipt = self.actions.reserve(context, action_key)
        self.actions.complete(
            context, receipt.model_copy(update={"business_ref": ref, "safe_reason": self._snapshot(context, values)})
        )
        return ref

    def reconcile(self, context, action_key):
        try:
            receipt = self.actions.read(context.owner, action_key)
        except NotFoundError:
            return None
        if receipt.business_ref:
            self._binding(context, receipt, receipt.business_ref, current=True)
        return receipt.business_ref

    def revise_inputs(self, context, result_ref):
        if self._confirmed(context, result_ref):
            try:
                checked = self.actions.read(context.owner, uuid5(result_ref.id, f"care-check:{context.revision - 1}"))
                self._binding(context, checked, result_ref)
            except NotFoundError:
                raise StaleVersionError("Check the confirmed care result before editing") from None
            if checked.safe_reason != "care_no_result_checked":
                raise StaleVersionError("Check the confirmed care result before editing")
        return {}

    def read_patient_result(self, context, result_ref, values=None):
        if values is None:
            raise ValidationError("Care result readback needs the current validated draft")
        ref = self._review_ref(context, values, result_ref)
        saved = self._saved_observation(context, values, ref)
        if saved:
            return saved
        actual = self._actual(context, values, ref)
        if actual:
            return actual[0]
        checked = self.actions.reserve(context, uuid5(ref.id, f"care-check:{context.revision}"))
        self.actions.complete(
            context, checked.model_copy(update={"business_ref": ref, "safe_reason": "care_no_result_checked"})
        )
        return ref

    def observe(self, context, result_ref):
        return OperationResult(state="pending", business_ref=result_ref)

    def run_patient_action(
        self, context: WorkflowContext, result_ref: BusinessRef, write: Callable[[], object]
    ) -> object:
        return self.clinical.run(context.owner, self.clinical.revision(context.owner), write)

    def run_bound_request(self, context, values, ref, capability, target, payload, write):
        if capability != context.capability_id:
            raise ValidationError("This patient endpoint does not match the current care task")
        self._binding(context, self.actions.read(context.owner, ref.id), ref)
        actual = self._actual(context, values, ref)
        if actual is None:
            self._current_snapshot(context, values, ref)
        if actual:
            expected_target = (
                ref.id
                if capability == "observation.add"
                else getattr(values, "observation_id", None)
                if capability.startswith("observation.")
                else getattr(values, "medication_id", None)
                if capability == "inventory.count"
                else getattr(values, "task_id", None)
            )
            # Patient payload must still be the original reviewed request on replay.
            if target != expected_target:
                raise ValidationError("The patient target differs from this review")
        review = (
            {"target_id": str(target) if target else None, "payload": {}}
            if capability == "observation.delete"
            else self.drafts.review(context, values, ref.id)
            if not actual or not capability.startswith("followup.")
            else None
        )
        if review is not None and review["target_id"] != (str(target) if target else None):
            raise ValidationError("The patient target differs from this review")
        if payload is not None:
            if not payload.confirmed:
                raise ValidationError("Confirm the patient care review before saving")
            expected = review["payload"] if review else self._original_update(context, values, ref)
            received = payload.model_dump(
                mode="json", exclude_unset=capability.startswith("followup.") and capability != "followup.add"
            )
            for key in ("confirmed", "historical_confirmed"):
                received.pop(key, None)
            expected = {
                key: value for key, value in expected.items() if key not in {"confirmed", "historical_confirmed"}
            }
            if received != expected:
                raise StaleVersionError("Patient fields changed; apply them to a new care review first")
        if actual:
            if capability == "observation.delete":
                return {"deleted": True}
            if capability == "inventory.count":
                return self.care.inventory(context.owner, values.medication_id, context.timezone)
            if capability.startswith("followup."):
                return self.drafts.task(context.owner, ref.id if capability == "followup.add" else values.task_id)
            if capability in {"observation.add", "observation.edit"}:
                return self.observations.get(
                    context.owner, ref.id if capability == "observation.add" else values.observation_id
                )
            return next(row for row in self.care.barriers(context.owner) if row.id == ref.id)
        if capability != "observation.delete" and self._actual(context, values, ref, require_receipt=False):
            raise StaleVersionError("This request ID already belongs to a different patient action")
        operation = self.actions.reserve(context, uuid5(ref.id, "care-patient-confirmation"))
        self.actions.complete(
            context, operation.model_copy(update={"business_ref": ref, "safe_reason": "care_patient_confirmed"})
        )
        result = write()
        if capability == "observation.delete":
            self.actions.complete(
                context, operation.model_copy(update={"business_ref": ref, "safe_reason": "care_deleted"})
            )
        if capability in {"observation.add", "observation.edit"}:
            target_id = ref.id if capability == "observation.add" else values.observation_id
            actual_record = self.observations.get(context.owner, target_id)
            payload_values = values.model_dump(exclude={"observation_id"})
            expected_record = ObservationInput(id=target_id, **payload_values).model_dump(
                mode="json", exclude={"confirmed"})
            if actual_record is None or any(actual_record.model_dump(mode="json").get(key) != value
                                             for key, value in expected_record.items()):
                raise StaleVersionError("The actual saved observation could not be verified")
            self.actions.complete(
                context, operation.model_copy(update={"business_ref": ref, "safe_reason": "care_saved"})
            )
        return result

    def validate_current_request(self, context, values, ref, target, payload):
        """Validate one current fresh patient request without invoking a writer."""
        if ref.kind != "care_review" or context.capability_id not in self.write_ids:
            raise ValidationError("Use the current independent care review")
        self._binding(context,self.actions.read(context.owner,ref.id),ref)
        self._current_snapshot(context,values,ref)
        review=self.drafts.review(context,values,ref.id)
        if review["target_id"]!=(str(target) if target else None):
            raise ValidationError("Patient target differs from this care review")
        if payload is not None:
            if payload.confirmed is not True:
                raise ValidationError("Confirm this independent patient care review")
            received=payload.model_dump(mode="json",exclude_unset=context.capability_id.startswith("followup.")
                and context.capability_id!="followup.add")
            expected=review["payload"]
            ignored={"confirmed","historical_confirmed"}
            if ({key:value for key,value in received.items() if key not in ignored}
                !={key:value for key,value in expected.items() if key not in ignored}):
                raise StaleVersionError("Patient inputs differ from the current saved care review")
        if context.capability_id!="observation.delete" and self._actual(context,values,ref,require_receipt=False):
            raise StaleVersionError("Native request ID is already used; inspect its original receipt")
        return review

    def review_snapshot(self,context,values):
        """Opaque current native-state fingerprint, never a write authorization."""
        if context.capability_id=='inventory.count':
            value=self.care.inventory(context.owner,values.medication_id,context.timezone).model_dump(mode='json')
        elif context.capability_id.startswith('followup.') and getattr(values,'task_id',None) is not None:
            value=self.drafts.task(context.owner,values.task_id).model_dump(mode='json')
        else:
            value=self._snapshot(context,values)
        return hashlib.sha256(
            json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        ).hexdigest()

    def confirmation_request(self, context, values, ref, *, recorded=False):
        """Public native request projection; recorded mode only reconstructs existing history."""
        if context.capability_id == "observation.delete":
            return {"target_id":str(values.observation_id), "payload":{}}
        if recorded and context.capability_id.startswith("followup.") and context.capability_id != "followup.add":
            return {"target_id":str(values.task_id), "payload":self._original_update(context, values, ref)}
        return self.drafts.review(context, values, ref.id)

    def _original_update(self, context, values, ref):
        # Reconstruct the original version from the immutable pre-change history.
        if context.capability_id == "followup.add":
            return self.drafts.review(context, values, ref.id)["payload"]
        from ...contracts.care_workflow import CARE_CHANGE_STATUS
        from ...contracts.long_term import TaskUpdate

        previous = self.drafts.task(context.owner, values.task_id)
        index = next(index for index, row in enumerate(previous.history) if row.id == ref.id)
        prior = previous.history[index - 1]
        data = self.drafts.change_fields(context.owner, values, prior.notes)
        status = CARE_CHANGE_STATUS.get(
            context.capability_id,
            values.status or ("open" if prior.status in {"completed", "cancelled"} else prior.status),
        )
        return TaskUpdate(id=ref.id, status=status, **data).model_dump(mode="json", exclude_unset=True)
