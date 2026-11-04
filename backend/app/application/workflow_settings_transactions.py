"""Current settings reviews bridge patient HTTP and the typed domain transaction."""

from uuid import uuid5

from ..contracts.assistant_workflows import BusinessRef, Preparation, WorkflowRepository, validate_workflow_values
from ..contracts.caregivers import CaregiverCreate, CaregiverDetails
from ..contracts.patient_feedback import FeedbackInput
from ..contracts.preferences import PreferenceUpdate
from ..contracts.workflow_coordination import BusinessReceiptReader
from ..contracts.workflow_persistence import WorkflowWriteBinding
from ..contracts.workflow_settings_writes import (
    CreateContact,
    DeleteContact,
    EditContact,
    PrepareSettingsReview,
    SavePreferences,
    SettingsWorkflowWritePort,
    SubmitFeedback,
)
from ..domain.errors import NotFoundError, ProviderUnavailableError, StaleVersionError, ValidationError


class SettingsWorkflowTransactions:
    capability_ids = frozenset(
        {
            "preference.language",
            "preference.text",
            "preference.voice",
            "preference.reminder",
            "preference.privacy",
            "preference.timezone",
            "profile.edit",
            "caregiver.add",
            "caregiver.edit",
            "caregiver.delete",
            "feedback.submit",
        }
    )

    def __init__(
        self,
        *,
        writes: SettingsWorkflowWritePort,
        tasks: WorkflowRepository,
        receipts: BusinessReceiptReader,
    ):
        self._writes, self._tasks, self._receipts = writes, tasks, receipts

    def prepare(self, task, expected_revision, action_key, run_binding=None):
        if task.capability_id not in self.capability_ids or task.save_mode != "allowed":
            raise ValidationError("Use the saved typed settings workflow")
        prior = self._writes.lookup(task.owner, action_key)
        if prior is not None and (
            prior.task_id != task.id
            or prior.capability_id != task.capability_id
            or prior.outcome != "prepared"
            or prior.binding_revision != expected_revision + 1
            or prior.business_ref != BusinessRef(kind="settings_review", id=action_key, version=1)
        ):
            raise StaleVersionError("Preparation event belongs to another task or revision")
        if prior is not None:
            return prior  # A recorded preparation is recovered read-only, including after its chat run expires.
        if prior is None and task.revision != expected_revision:
            raise StaleVersionError("Settings task changed before preparation")
        b = WorkflowWriteBinding(
            task_id=task.id,
            task_revision=expected_revision,
            capability_id=task.capability_id,
            action_key=action_key,
            prepared_ref=BusinessRef(kind="settings_review", id=action_key, version=1),
            expected_domain_revision=prior.domain_revision if prior else self._writes.revision(task.owner),
            run_binding=run_binding,
        )
        result = self._writes.prepare(task.owner, PrepareSettingsReview(binding=b))
        if (
            result.receipt.owner != task.owner
            or result.receipt.task_id != task.id
            or result.receipt.business_ref != b.prepared_ref
            or result.receipt.binding_revision != expected_revision + 1
            or result.receipt.outcome != "prepared"
        ):
            raise StaleVersionError("Actual settings preparation receipt differs from its task")
        return result.receipt

    def _preparation(self, task, revision):
        rows = [
            r
            for r in self._receipts.task_receipts(task.owner, task.id)
            if r.capability_id == task.capability_id
            and r.outcome == "prepared"
            and r.binding_revision == revision
            and r.business_ref.kind == "settings_review"
        ]
        if len(rows) != 1:
            raise StaleVersionError("Current independent settings review unavailable")
        return rows[0]

    def _command(self, task, prep, payload=None, *, supplied=False, target=None, confirmed=True):
        f = validate_workflow_values(task.capability_id, task.fields)
        ref, cap = prep.business_ref, task.capability_id
        b = WorkflowWriteBinding(
            task_id=task.id,
            task_revision=prep.binding_revision,
            capability_id=cap,
            action_key=uuid5(ref.id, "settings-patient-confirmation"),
            prepared_ref=ref,
            expected_domain_revision=prep.domain_revision,
        )
        if cap.startswith("preference.") or cap == "profile.edit":
            expected_target = None
            native = (
                PreferenceUpdate.model_validate(payload.model_dump(exclude_unset=True))
                if supplied
                else PreferenceUpdate.model_validate(f.model_dump(exclude={"previous"}, exclude_none=True))
            )
            cmd = SavePreferences(binding=b, previous=f.previous, values=native, confirmed=confirmed)
        elif cap == "feedback.submit":
            expected_target = ref.id
            native = payload if supplied else FeedbackInput(id=ref.id, category=f.category, message=f.message)
            cmd = SubmitFeedback(binding=b, values=native, confirmed=confirmed)
        elif cap == "caregiver.add":
            expected_target = ref.id
            native = (
                payload
                if supplied
                else CaregiverCreate(id=ref.id, **{k: getattr(f, k) for k in CaregiverDetails.model_fields})
            )
            cmd = CreateContact(binding=b, values=native, confirmed=confirmed)
        else:
            expected_target = f.contact_id
            args = dict(
                binding=b,
                contact_id=f.contact_id,
                previous=f.previous,
                previous_updated_at=f.previous_updated_at,
                confirmed=confirmed,
            )
            if cap == "caregiver.delete":
                if supplied and payload is not None:
                    raise ValidationError("Contact deletion accepts no replacement details")
                cmd = DeleteContact(**args)
            else:
                native = (
                    payload
                    if supplied
                    else CaregiverDetails(**{k: getattr(f, k) for k in CaregiverDetails.model_fields})
                )
                cmd = EditContact(**args, values=native)
        if supplied and target != expected_target:
            raise StaleVersionError("Patient endpoint target differs from the reviewed owned target")
        return cmd

    def apply_native(self, owner, task_id, revision, capability, target, payload, confirmed):
        task = self._tasks.get(owner, task_id)
        if task.capability_id != capability or capability not in self.capability_ids or confirmed is not True:
            raise StaleVersionError("Independently confirm the exact current settings operation")
        prep = self._preparation(task, revision)
        cmd = self._command(task, prep, payload, supplied=True, target=target, confirmed=confirmed)
        result = self._writes.apply(owner, cmd)
        if cmd.kind == "feedback":
            return {"id": result.result.id, "created_at": result.result.created_at, "status": "received"}
        if cmd.kind == "delete_contact":
            return {"deleted": True}
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
            raise StaleVersionError("Completed settings task has no actual native transaction receipt")
        receipt = max(receipts, key=lambda r: r.binding_revision)
        prep = self._preparation(task, receipt.binding_revision - 1)
        cmd = self._command(task, prep)
        if receipt.action_key != cmd.binding.action_key:
            raise StaleVersionError("Actual settings receipt is not bound to its independent confirmation")
        try:
            result = self._writes.read(task.owner, cmd)
        except (StaleVersionError, NotFoundError, ProviderUnavailableError):
            return Preparation(
                input_fields=task.fields,
                result_ref=receipt.business_ref,
                workflow_state="completed",
                prompt_key="assistant.feedback.check_result"
                if cmd.kind == "feedback"
                else "assistant.settings.check_result",
                view_fields={"actual_result_available": False},
            )
        if result.receipt != receipt:
            raise StaleVersionError("Actual settings result has another receipt")
        row = result.result
        visible = (
            {"current_preferences": row.model_dump(mode="json", exclude={"patient_id", "created_at", "updated_at"})}
            if cmd.kind == "preferences"
            else {"current_feedback": row.model_dump(mode="json", exclude={"patient_id"})}
            if cmd.kind == "feedback"
            else {"current_contact": row.model_dump(mode="json", exclude={"patient_id"}) if row else None}
        )
        return Preparation(
            input_fields=task.fields,
            result_ref=receipt.business_ref,
            workflow_state="completed",
            prompt_key="assistant.feedback.saved" if cmd.kind == "feedback" else "assistant.settings.saved",
            view_fields=visible,
        )
