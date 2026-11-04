"""Native reminder transactions; no sender, subscription or schedule repository."""

import hashlib
import json
from contextlib import contextmanager
from copy import deepcopy

from ..contracts.assistant_workflows import (
    ActionReceipt,
    BusinessRef,
    WorkflowContext,
    WorkflowUpdate,
    validate_workflow_values,
)
from ..contracts.preferences import Preferences
from ..contracts.reminders import ReminderDTO
from ..contracts.workflow_persistence import BusinessWriteReceipt, NativeWriteResult
from ..contracts.workflow_reminder_writes import (
    REMINDER_WRITE_COMMAND,
    LocalReminderPort,
    PrepareReminderReview,
    ReminderNativeResult,
    reminder_command_body,
)
from ..contracts.workflow_settings_writes import LocalPreferencePort
from ..domain.errors import (
    DuplicateEventError,
    NotFoundError,
    ProviderUnavailableError,
    StaleVersionError,
    ValidationError,
)


def reminder_digest(value):
    if hasattr(value, "model_dump"):
        value = reminder_command_body(value) if hasattr(value, "binding") else value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class MemoryReminderWorkflowWrites:
    def __init__(
        self,
        *,
        state,
        store,
        clock,
        tasks,
        controls,
        adapter,
        reminders,
        reminder_storage: LocalReminderPort,
        preferences,
        preference_storage: LocalPreferencePort,
    ):
        self._state, self._store, self._clock, self._tasks, self._controls = state, store, clock, tasks, controls
        self._adapter, self._reminders, self._preferences = adapter, reminders, preferences
        self._reminder_storage, self._preference_storage = reminder_storage, preference_storage

    def revision(self, owner):
        with self._store.clinical.lock:
            return (
                self._store.clinical.revisions.get(owner, 0)
                + self._reminder_storage.revision(owner)
                + self._preference_storage.revision(owner)
            )

    def lookup(self, owner, action_key):
        with self._state.lock:
            return self._state.business_receipts.get((owner, action_key))

    @contextmanager
    def _transaction(self):
        maps = [
            self._state.tasks,
            self._state.controls,
            self._state.events,
            self._state.actions,
            self._state.business_receipts,
            self._state.reminder_commands,
            self._state.reminder_preparations,
        ]
        old, used = [deepcopy(value) for value in maps], set(self._state.used)
        with self._preference_storage.local_transaction(), self._reminder_storage.local_transaction():
            try:
                yield
            except BaseException:
                for current, prior in zip(maps, old, strict=True):
                    current.clear()
                    current.update(prior)
                self._state.used.clear()
                self._state.used.update(used)
                raise

    def _run_current(self, owner, b):
        if b.run_binding is not None:
            self._state.require_durable_run(owner, b.run_binding, self._clock.now())

    def _current(self, owner, b):
        task, ctl = self._tasks.get(owner, b.task_id), self._controls.get(owner, b.task_id)
        if (
            b.capability_id not in {"reminder.snooze", "reminder.settings"}
            or task.capability_id != b.capability_id
            or ctl.capability_id != b.capability_id
            or task.revision != b.task_revision
            or ctl.revision != task.revision
            or task.save_mode != "allowed"
            or ctl.mode != "allowed"
            or ctl.revoked
            or ctl.status != "idle"
            or task.attachment_ids
            or self.revision(owner) != b.expected_domain_revision
        ):
            raise StaleVersionError("Current saved reminder review changed")
        if b.prepared_ref.kind != "reminder_review" or b.prepared_ref.version != 1:
            raise ValidationError("Use the current independently confirmed reminder review")
        self._run_current(owner, b)
        prefs = self._preferences.get(owner)
        context = WorkflowContext(
            owner=owner,
            task_id=task.id,
            revision=task.revision,
            capability_id=task.capability_id,
            timezone=prefs.timezone,
            language=prefs.preferred_language,
        )
        values = validate_workflow_values(task.capability_id, task.fields)
        snapshot = reminder_digest(self._adapter.review_snapshot(context, values))
        return task, values, snapshot

    def _advance(self, owner, task, b, ref, preparing):
        self._run_current(owner, b)
        self._tasks.cas(
            owner,
            task.id,
            task.revision,
            b.action_key,
            WorkflowUpdate(
                state="awaiting_confirmation" if preparing else "completed",
                save_mode="allowed",
                storage_state="saved",
                fields=task.fields,
                missing_fields=(),
                attachment_ids=(),
                business_refs=(ref,),
            ),
        )
        receipt = BusinessWriteReceipt(
            owner=owner,
            action_key=b.action_key,
            task_id=task.id,
            capability_id=task.capability_id,
            binding_revision=task.revision + 1,
            business_ref=ref,
            domain_revision=self.revision(owner),
            outcome="prepared" if preparing else "applied",
            recorded_at=self._clock.now(),
        )
        self._state.business_receipts[owner, b.action_key] = receipt
        return receipt

    def _prior(self, owner, command, digest):
        b = command.binding
        receipt = self.lookup(owner, b.action_key)
        if receipt is None:
            return None
        meta = self._state.reminder_commands.get((owner, b.action_key))
        if meta is None or meta[0] != digest:
            raise DuplicateEventError("Action belongs to another reminder command")
        result = (
            None
            if command.kind == "prepare_reminder"
            else self._preferences.get(owner)
            if command.kind == "settings"
            else self._reminders.get_saved(owner, receipt.business_ref.id)
        )
        if reminder_digest(result) != meta[1]:
            raise StaleVersionError("Actual reminder result changed; retain its historical receipt")
        return NativeWriteResult(receipt=receipt, result=result)

    def prepare(self, owner, command):
        command = PrepareReminderReview.model_validate(command.model_dump())
        b = command.binding
        digest = reminder_digest(command)
        with self._state.lock, self._store.clinical.lock, self._transaction():
            prior = self._prior(owner, command, digest)
            if prior is not None:
                return prior
            task, _values, snapshot = self._current(owner, b)
            old = (
                self._state.reminder_preparations.get((owner, task.business_refs[0].id))
                if len(task.business_refs) == 1
                else None
            )
            stale = old is not None and (old[1] < task.revision or old[3] != self.revision(owner) or old[4] != snapshot)
            if b.prepared_ref.id != b.action_key or not (
                task.state == "ready_for_review" or task.state == "awaiting_confirmation" and stale
            ):
                raise StaleVersionError("Prepare a fresh current reminder draft")
            if (owner, b.action_key) in self._state.actions:
                raise DuplicateEventError("Reminder preparation cannot replace another action")
            self._state.actions[owner, b.action_key] = ActionReceipt(
                owner=owner,
                action_key=b.action_key,
                task_id=task.id,
                capability_id=task.capability_id,
                binding_revision=task.revision,
                state="succeeded",
                business_ref=b.prepared_ref,
                clinical_revision=self._store.clinical.revisions.get(owner, 0),
                safe_reason="reminder_prepared",
                updated_at=self._clock.now(),
            )
            receipt = self._advance(owner, task, b, b.prepared_ref, True)
            self._state.reminder_preparations[owner, b.action_key] = (
                task.id,
                receipt.binding_revision,
                task.capability_id,
                self.revision(owner),
                snapshot,
            )
            self._state.reminder_commands[owner, b.action_key] = digest, reminder_digest(None)
            return NativeWriteResult(receipt=receipt, result=None)

    def apply(self, owner, command):
        command = REMINDER_WRITE_COMMAND.validate_python(reminder_command_body(command))
        b = command.binding
        digest = reminder_digest(command)
        with self._state.lock, self._store.clinical.lock, self._transaction():
            prior = self._prior(owner, command, digest)
            if prior is not None:
                return prior
            task, values, snapshot = self._current(owner, b)
            expected = task.id, task.revision, task.capability_id, self.revision(owner), snapshot
            if (
                task.state != "awaiting_confirmation"
                or task.business_refs != (b.prepared_ref,)
                or self._state.reminder_preparations.get((owner, b.prepared_ref.id)) != expected
            ):
                raise StaleVersionError("Actual reminder preparation changed")
            if command.kind == "snooze":
                if b.capability_id != "reminder.snooze" or command.values != values:
                    raise StaleVersionError("Confirm the exact existing occurrence and delay")
                result = self._reminders.snooze(
                    patient_id=owner, occurrence_id=values.occurrence_id, minutes=values.minutes
                )
                ref = BusinessRef(kind="dose_occurrence", id=values.occurrence_id)
            else:
                if (
                    b.capability_id != "reminder.settings"
                    or command.previous_enabled != values.previous_enabled
                    or command.previous_lead_minutes != values.previous_lead_minutes
                    or command.previous_timezone != values.previous_timezone
                    or command.values.model_dump(exclude_none=True)
                    != {
                        "reminders_enabled": values.reminders_enabled,
                        "reminder_lead_minutes": values.reminder_lead_minutes,
                    }
                ):
                    raise StaleVersionError("Confirm the exact reminder preference snapshot")
                result = self._preferences.save(owner, command.values)
                ref = BusinessRef(kind="preference", id=owner)
            receipt = self._advance(owner, task, b, ref, False)
            self._state.reminder_commands[owner, b.action_key] = digest, reminder_digest(result)
            return NativeWriteResult(receipt=receipt, result=result)

    def read(self, owner, command):
        command = REMINDER_WRITE_COMMAND.validate_python(reminder_command_body(command))
        with (self._state.lock, self._store.clinical.lock, self._preference_storage.local_transaction(),
              self._reminder_storage.local_transaction()):
            result = self._prior(owner, command, reminder_digest(command))
            if result is None:
                raise NotFoundError("Actual owned reminder receipt unavailable")
            return result


class SupabaseReminderWorkflowWrites:
    def __init__(self, *, data, receipts):
        self._data, self._receipts = data, receipts

    def lookup(self, owner, action_key):
        self._data.check_patient(owner)
        return self._receipts.read_receipt(owner, action_key)

    def revision(self, owner):
        self._data.check_patient(owner)
        raw = self._data.request("POST", "/rest/v1/rpc/assistant_reminder_revision", body={})
        if (
            not isinstance(raw, dict)
            or set(raw) != {"revision"}
            or type(raw["revision"]) is not int
            or raw["revision"] < 0
        ):
            raise ProviderUnavailableError("Current native reminder revision unavailable")
        return raw["revision"]

    @staticmethod
    def _validate(owner, command, result, prior):
        b, r, row = command.binding, result.receipt, result.result
        if (
            r.owner != owner
            or r.task_id != b.task_id
            or r.capability_id != b.capability_id
            or r.action_key != b.action_key
            or r.binding_revision != b.task_revision + 1
            or prior is not None
            and prior != r
        ):
            raise ValueError
        if command.kind == "prepare_reminder":
            if row is not None or r.outcome != "prepared" or r.business_ref != b.prepared_ref:
                raise ValueError
            return
        if r.outcome != "applied" or row is None or row.patient_id != owner:
            raise ValueError
        if command.kind == "snooze":
            if (
                b.capability_id != "reminder.snooze"
                or not isinstance(row, ReminderDTO)
                or row.occurrence_id != command.values.occurrence_id
                or row.remind_at.utcoffset() is None
                or r.business_ref != BusinessRef(kind="dose_occurrence", id=command.values.occurrence_id)
            ):
                raise ValueError
            # The native transaction validates the actual delay/deadline. Its
            # later receipt timestamp is not the start of the snooze operation;
            # readback must preserve the saved instant after a slow/lost reply.
        elif (
            b.capability_id != "reminder.settings"
            or not isinstance(row, Preferences)
            or r.business_ref != BusinessRef(kind="preference", id=owner)
            or row.timezone != command.previous_timezone
            or any(getattr(row, key) != value for key, value in command.values.model_dump(exclude_none=True).items())
        ):
            raise ValueError

    def _request(self, owner, command, *, read_only=False):
        self._data.check_patient(owner)
        prior = self.lookup(owner, command.binding.action_key)
        if read_only and prior is None:
            raise NotFoundError("Actual owned reminder receipt unavailable")
        endpoint = (
            "assistant_reminder_read"
            if prior is not None
            else "assistant_reminder_prepare"
            if command.kind == "prepare_reminder"
            else "assistant_reminder_write"
        )
        raw = self._data.request("POST", "/rest/v1/rpc/" + endpoint, body={"p_command": reminder_command_body(command)})
        if isinstance(raw, dict) and set(raw) == {"error"}:
            errors = {
                "stale": StaleVersionError,
                "duplicate": DuplicateEventError,
                "invalid": ValidationError,
                "not_found": NotFoundError,
            }
            code = raw["error"] if isinstance(raw["error"], str) else "unavailable"
            raise errors.get(code, ProviderUnavailableError)(
                "Native reminder result unavailable; inspect its owned receipt"
            )
        try:
            if not isinstance(raw, dict) or set(raw) != {"result", "replayed"} or type(raw["replayed"]) is not bool:
                raise ValueError
            result = NativeWriteResult[ReminderNativeResult].model_validate(raw["result"])
            self._validate(owner, command, result, prior)
            return result
        except (ValueError, TypeError, AttributeError):
            raise ProviderUnavailableError("Native reminder response differs from its current owned command") from None

    def prepare(self, owner, command):
        self._data.check_patient(owner)
        return self._request(owner, PrepareReminderReview.model_validate(command.model_dump()))

    def apply(self, owner, command):
        self._data.check_patient(owner)
        return self._request(owner, REMINDER_WRITE_COMMAND.validate_python(reminder_command_body(command)))

    def read(self, owner, command):
        self._data.check_patient(owner)
        return self._request(
            owner, REMINDER_WRITE_COMMAND.validate_python(reminder_command_body(command)), read_only=True
        )
