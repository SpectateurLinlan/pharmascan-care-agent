"""Bridge independently confirmed reminder APIs to their owned transaction."""

from uuid import uuid5

from ..contracts.assistant_workflows import BusinessRef, Preparation, WorkflowRepository, validate_workflow_values
from ..contracts.preferences import PreferenceUpdate
from ..contracts.workflow_coordination import BusinessReceiptReader
from ..contracts.workflow_persistence import WorkflowWriteBinding
from ..contracts.workflow_reminder_writes import (
    PrepareReminderReview,
    ReminderWorkflowWritePort,
    SaveReminderSettings,
    SnoozeReminder,
)
from ..domain.errors import NotFoundError, ProviderUnavailableError, StaleVersionError, ValidationError


class ReminderWorkflowTransactions:
    capability_ids = frozenset({"reminder.snooze", "reminder.settings"})

    def __init__(
        self, *, writes: ReminderWorkflowWritePort, tasks: WorkflowRepository, receipts: BusinessReceiptReader
    ):
        self._writes, self._tasks, self._receipts = writes, tasks, receipts

    def prepare(self, task, expected_revision, action_key, run_binding=None):
        if task.capability_id not in self.capability_ids or task.save_mode != "allowed":
            raise ValidationError("Use the saved reminder workflow")
        prior = self._writes.lookup(task.owner, action_key)
        ref = BusinessRef(kind="reminder_review", id=action_key, version=1)
        if prior is not None:
            if (
                prior.task_id != task.id
                or prior.capability_id != task.capability_id
                or prior.outcome != "prepared"
                or prior.binding_revision != expected_revision + 1
                or prior.business_ref != ref
            ):
                raise StaleVersionError("Reminder preparation event belongs to another scope")
            return prior
        if task.revision != expected_revision:
            raise StaleVersionError("Reminder task changed before preparation")
        b = WorkflowWriteBinding(
            task_id=task.id,
            task_revision=expected_revision,
            capability_id=task.capability_id,
            action_key=action_key,
            prepared_ref=ref,
            expected_domain_revision=self._writes.revision(task.owner),
            run_binding=run_binding,
        )
        result = self._writes.prepare(task.owner, PrepareReminderReview(binding=b))
        if (
            result.receipt.owner != task.owner
            or result.receipt.task_id != task.id
            or result.receipt.business_ref != ref
            or result.receipt.outcome != "prepared"
            or result.receipt.binding_revision != expected_revision + 1
        ):
            raise StaleVersionError("Actual reminder preparation receipt differs from its task")
        return result.receipt

    def _preparation(self, task, revision):
        rows = [
            r
            for r in self._receipts.task_receipts(task.owner, task.id)
            if r.capability_id == task.capability_id
            and r.outcome == "prepared"
            and r.binding_revision == revision
            and r.business_ref.kind == "reminder_review"
        ]
        if len(rows) != 1:
            raise StaleVersionError("Current independent reminder preparation unavailable")
        return rows[0]

    def _command(self, task, prep, payload=None, *, supplied=False, confirmed=True):
        f = validate_workflow_values(task.capability_id, task.fields)
        b = WorkflowWriteBinding(
            task_id=task.id,
            task_revision=prep.binding_revision,
            capability_id=task.capability_id,
            action_key=uuid5(prep.business_ref.id, "reminder-patient-confirmation"),
            prepared_ref=prep.business_ref,
            expected_domain_revision=prep.domain_revision,
        )
        if task.capability_id == "reminder.snooze":
            expected = {"occurrence_id": str(f.occurrence_id), "minutes": f.minutes}
            cmd = SnoozeReminder(binding=b, values=f, confirmed=confirmed)
        else:
            expected = {"reminders_enabled": f.reminders_enabled, "reminder_lead_minutes": f.reminder_lead_minutes}
            cmd = SaveReminderSettings(
                binding=b,
                values=PreferenceUpdate(**expected),
                previous_enabled=f.previous_enabled,
                previous_lead_minutes=f.previous_lead_minutes,
                previous_timezone=f.previous_timezone,
                confirmed=confirmed,
            )
        if supplied and (payload is None or payload.model_dump(mode="json", exclude_unset=True) != expected):
            raise StaleVersionError("Confirm the exact owned occurrence/settings and reviewed delay")
        return cmd

    def apply_native(self, owner, task_id, revision, capability, payload, confirmed):
        task = self._tasks.get(owner, task_id)
        if task.capability_id != capability or capability not in self.capability_ids or confirmed is not True:
            raise StaleVersionError("Independently confirm the exact reminder operation")
        prep = self._preparation(task, revision)
        return self._writes.apply(owner, self._command(task, prep, payload, supplied=True, confirmed=confirmed)).result

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
            raise StaleVersionError("Completed reminder task has no actual native receipt")
        receipt = max(receipts, key=lambda r: r.binding_revision)
        cmd = self._command(task, self._preparation(task, receipt.binding_revision - 1))
        if receipt.action_key != cmd.binding.action_key:
            raise StaleVersionError("Reminder receipt differs from its independent confirmation")
        try:
            result = self._writes.read(task.owner, cmd)
        except (StaleVersionError, NotFoundError, ProviderUnavailableError):
            return Preparation(
                input_fields=task.fields,
                result_ref=receipt.business_ref,
                workflow_state="completed",
                prompt_key="assistant.reminder.check_result",
                view_fields={"actual_result_available": False},
            )
        if result.receipt != receipt:
            raise StaleVersionError("Actual reminder result has another receipt")
        visible = (
            {"remind_at": result.result.remind_at.isoformat()}
            if cmd.kind == "snooze"
            else {
                "current_settings": {
                    "reminders_enabled": result.result.reminders_enabled,
                    "reminder_lead_minutes": result.result.reminder_lead_minutes,
                },
                "timezone": result.result.timezone,
            }
        )
        return Preparation(
            input_fields=task.fields,
            result_ref=receipt.business_ref,
            workflow_state="completed",
            prompt_key="assistant.reminder.saved",
            view_fields=visible,
        )
