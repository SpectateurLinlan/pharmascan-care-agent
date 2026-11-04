"""Independently confirmed care API requests share the native/task transaction."""

from uuid import uuid5

from ..contracts.assistant_workflows import (
    BusinessRef,
    Preparation,
    WorkflowContext,
    WorkflowRepository,
    validate_workflow_values,
)
from ..contracts.long_term import BarrierInput, CareTaskInput, StockInput, TaskUpdate
from ..contracts.observations import ObservationInput
from ..contracts.workflow_care_writes import (
    CareWorkflowWritePort,
    CreateFollowup,
    DeleteObservation,
    PrepareCareReview,
    RecordBarrier,
    RecordStock,
    SaveObservation,
    UpdateFollowup,
)
from ..contracts.workflow_coordination import BusinessReceiptReader
from ..contracts.workflow_persistence import WorkflowWriteBinding
from ..domain.errors import NotFoundError, ProviderUnavailableError, StaleVersionError, ValidationError
from .assistant_capabilities.care import CareAdapter
from .long_term import LongTermCareService
from .preferences import PreferenceService


class CareWorkflowTransactions:
    capability_ids = frozenset(
        {
            "observation.add",
            "observation.edit",
            "observation.delete",
            "inventory.count",
            "barrier.add",
            "followup.add",
            "followup.edit",
            "followup.contacted",
            "followup.complete",
            "followup.defer",
            "followup.cancel",
        }
    )

    def __init__(
        self,
        *,
        writes: CareWorkflowWritePort,
        tasks: WorkflowRepository,
        receipts: BusinessReceiptReader,
        adapter: CareAdapter,
        preferences: PreferenceService,
        care: LongTermCareService,
    ):
        self._writes, self._tasks, self._receipts = writes, tasks, receipts
        self._adapter, self._preferences, self._care = adapter, preferences, care

    def prepare(self, task, expected_revision, action_key, run_binding=None):
        if task.capability_id not in self.capability_ids or task.save_mode != "allowed":
            raise ValidationError("Use the saved care workflow")
        ref = BusinessRef(kind="care_review", id=action_key, version=1)
        prior = self._writes.lookup(task.owner, action_key)
        if prior is not None:
            if (
                prior.task_id != task.id
                or prior.capability_id != task.capability_id
                or prior.outcome != "prepared"
                or prior.binding_revision != expected_revision + 1
                or prior.business_ref != ref
            ):
                raise StaleVersionError("Care preparation event belongs to another scope")
            return prior
        if task.revision != expected_revision:
            raise StaleVersionError("Care task changed before preparation")
        b = WorkflowWriteBinding(
            task_id=task.id,
            task_revision=expected_revision,
            capability_id=task.capability_id,
            action_key=action_key,
            prepared_ref=ref,
            expected_domain_revision=self._writes.revision(task.owner),
            run_binding=run_binding,
        )
        result = self._writes.prepare(task.owner, PrepareCareReview(binding=b))
        if (
            result.receipt.owner != task.owner
            or result.receipt.task_id != task.id
            or result.receipt.business_ref != ref
            or result.receipt.binding_revision != expected_revision + 1
            or result.receipt.outcome != "prepared"
        ):
            raise StaleVersionError("Actual care preparation receipt differs from the task")
        return result.receipt

    def _preparation(self, task, revision):
        rows = [
            r
            for r in self._receipts.task_receipts(task.owner, task.id)
            if r.capability_id == task.capability_id
            and r.outcome == "prepared"
            and r.binding_revision == revision
            and r.business_ref.kind == "care_review"
        ]
        if len(rows) != 1:
            raise StaleVersionError("Current independent care preparation unavailable")
        return rows[0]

    def _command(self, task, prep, payload=None, *, supplied=False):
        f = validate_workflow_values(task.capability_id, task.fields)
        cap = task.capability_id
        b = WorkflowWriteBinding(
            task_id=task.id,
            task_revision=prep.binding_revision,
            capability_id=cap,
            action_key=uuid5(prep.business_ref.id, "care-patient-confirmation"),
            prepared_ref=prep.business_ref,
            expected_domain_revision=prep.domain_revision,
        )
        if not supplied and cap != "observation.delete":
            prefs = self._preferences.get(task.owner)
            context = WorkflowContext(
                owner=task.owner,
                task_id=task.id,
                revision=prep.binding_revision,
                capability_id=cap,
                timezone=prefs.timezone,
                language=prefs.preferred_language,
            )
            raw = self._adapter.confirmation_request(context, f, prep.business_ref, recorded=True)["payload"] | {
                "confirmed": True
            }
            schema = (
                ObservationInput
                if cap.startswith("observation.")
                else StockInput
                if cap == "inventory.count"
                else BarrierInput
                if cap == "barrier.add"
                else CareTaskInput
                if cap == "followup.add"
                else TaskUpdate
            )
            payload = schema.model_validate(raw)
        if cap == "observation.delete":
            if supplied and payload is not None:
                raise ValidationError("Observation deletion accepts no replacement data")
            return DeleteObservation(binding=b, observation_id=f.observation_id, confirmed=True)
        if payload is None or payload.confirmed is not True:
            raise StaleVersionError("Confirm the independent patient care review")
        if cap.startswith("observation."):
            return SaveObservation(binding=b, values=payload, confirmed=True)
        if cap == "inventory.count":
            return RecordStock(binding=b, medication_id=f.medication_id, values=payload, confirmed=True)
        if cap == "barrier.add":
            return RecordBarrier(binding=b, values=payload, confirmed=True)
        if cap == "followup.add":
            return CreateFollowup(binding=b, values=payload, confirmed=True)
        return UpdateFollowup(
            binding=b, task_id=f.task_id, expected_version=f.expected_version, values=payload, confirmed=True
        )

    def apply_native(self, owner, task_id, revision, allowed, target, payload):
        task = self._tasks.get(owner, task_id)
        if task.capability_id not in allowed or task.capability_id not in self.capability_ids:
            raise StaleVersionError("Patient endpoint does not match this care task")
        cmd = self._command(task, self._preparation(task, revision), payload, supplied=True)
        actual_target = (
            cmd.observation_id
            if cmd.kind == "delete_observation"
            else cmd.values.id
            if cmd.kind == "save_observation"
            else cmd.medication_id
            if cmd.kind == "stock"
            else cmd.task_id
            if cmd.kind == "update_followup"
            else None
        )
        if target != actual_target:
            raise StaleVersionError("Patient care target differs from its independent review")
        result = self._writes.apply(owner, cmd)
        if cmd.kind == "delete_observation":
            return {"deleted": True}
        if cmd.kind == "stock":
            return self._care.inventory(owner, cmd.medication_id, self._preferences.get(owner).timezone)
        return result.result

    def project(self, task):
        if task.state != "completed":
            return None
        receipts = [
            r
            for r in self._receipts.task_receipts(task.owner, task.id)
            if r.outcome == "applied"
            and r.capability_id == task.capability_id
            and r.binding_revision <= task.revision
            and task.business_refs == (r.business_ref,)
        ]
        if not receipts:
            raise StaleVersionError("Completed care task has no actual native receipt")
        receipt = max(receipts, key=lambda r: r.binding_revision)
        try:
            cmd = self._command(task, self._preparation(task, receipt.binding_revision - 1))
            if cmd.binding.action_key != receipt.action_key:
                raise StaleVersionError("Care receipt differs from independent confirmation")
            result = self._writes.read(task.owner, cmd)
        except (StaleVersionError, NotFoundError, ProviderUnavailableError, StopIteration):
            return Preparation(
                input_fields=task.fields,
                result_ref=receipt.business_ref,
                workflow_state="completed",
                prompt_key="assistant.care.check_result",
                view_fields={"actual_result_available": False},
            )
        if result.receipt != receipt:
            raise StaleVersionError("Actual care result has another receipt")
        native = result.result
        visible = {
            "actual_care_result": native.model_dump(mode="json", exclude={"patient_id"}) if native is not None else None
        }
        return Preparation(
            input_fields=task.fields,
            result_ref=receipt.business_ref,
            workflow_state="completed",
            prompt_key="assistant.care.saved",
            view_fields=visible,
        )
