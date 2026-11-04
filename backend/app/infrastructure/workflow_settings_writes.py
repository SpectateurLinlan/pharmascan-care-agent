"""Owned local profile/contact/feedback publication with minimal workflow receipts."""

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
from ..contracts.caregivers import CaregiverContact
from ..contracts.patient_feedback import PatientFeedback
from ..contracts.preferences import Preferences
from ..contracts.workflow_persistence import BusinessWriteReceipt, NativeWriteResult
from ..contracts.workflow_settings_writes import (
    SETTINGS_WRITE_COMMAND,
    LocalContactPort,
    LocalFeedbackPort,
    LocalPreferencePort,
    PrepareSettingsReview,
    SettingsNativeResult,
    settings_command_body,
)
from ..domain.errors import (
    DuplicateEventError,
    NotFoundError,
    ProviderUnavailableError,
    StaleVersionError,
    ValidationError,
)

PREFERENCE_CAPS = frozenset(
    {
        "preference.language",
        "preference.text",
        "preference.voice",
        "preference.reminder",
        "preference.privacy",
        "preference.timezone",
        "profile.edit",
    }
)
CAPABILITIES = {
    "preferences": PREFERENCE_CAPS,
    "create_contact": {"caregiver.add"},
    "edit_contact": {"caregiver.edit"},
    "delete_contact": {"caregiver.delete"},
    "feedback": {"feedback.submit"},
}
WRITE_CAPS = frozenset().union(*CAPABILITIES.values())


def settings_digest(value):
    if hasattr(value, "model_dump"):
        value = (
            settings_command_body(value)
            if getattr(value, "kind", None) == "preferences"
            else value.model_dump(mode="json")
        )
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class MemorySettingsWorkflowWrites:
    def __init__(
        self,
        *,
        state,
        store,
        clock,
        tasks,
        controls,
        adapters,
        preferences,
        preference_storage: LocalPreferencePort,
        contacts,
        contact_storage: LocalContactPort,
        feedback,
        feedback_storage: LocalFeedbackPort,
    ):
        self._state, self._store, self._clock, self._tasks, self._controls = state, store, clock, tasks, controls
        self._adapters, self._preferences, self._contacts, self._feedback = adapters, preferences, contacts, feedback
        self._preference_storage, self._contact_storage, self._feedback_storage = (
            preference_storage,
            contact_storage,
            feedback_storage,
        )

    def revision(self, owner):
        with self._store.clinical.lock:
            return (
                self._store.clinical.revisions.get(owner, 0)
                + self._preference_storage.revision(owner)
                + self._contact_storage.revision(owner)
                + self._feedback_storage.revision(owner)
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
            self._state.settings_commands,
            self._state.settings_preparations,
        ]
        old, used = [deepcopy(value) for value in maps], set(self._state.used)
        with (
            self._preference_storage.local_transaction(),
            self._contact_storage.local_transaction(),
            self._feedback_storage.local_transaction(),
        ):
            try:
                yield
            except BaseException:
                for current, saved in zip(maps, old, strict=True):
                    current.clear()
                    current.update(saved)
                self._state.used.clear()
                self._state.used.update(used)
                raise

    def _run_current(self, owner, binding):
        if binding.run_binding is not None:
            self._state.require_durable_run(owner, binding.run_binding, self._clock.now())

    def _current(self, owner, b):
        task, ctl = self._tasks.get(owner, b.task_id), self._controls.get(owner, b.task_id)
        if (
            task.capability_id not in WRITE_CAPS
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
            raise StaleVersionError("Current saved settings scope changed")
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
        if b.prepared_ref.kind != "settings_review" or b.prepared_ref.version != 1:
            raise ValidationError("A current independent settings review is required")
        snapshot = self._adapters[task.capability_id].review_snapshot(context, values, b.prepared_ref)
        return task, context, values, settings_digest(snapshot)

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

    def _read(self, owner, receipt, kind):
        if kind == "prepare_settings":
            return None
        ref = receipt.business_ref
        if kind == "preferences":
            result = self._preferences.get(owner)
        elif kind == "feedback":
            result = self._feedback.get(owner, ref.id)
        else:
            result = self._contacts.get(owner, ref.id)
        if (kind == "delete_contact") != (result is None):
            raise StaleVersionError("Actual settings result changed; retain the historical receipt")
        return result

    def _prior(self, owner, command, digest):
        receipt = self.lookup(owner, command.binding.action_key)
        if receipt is None:
            return None
        metadata = self._state.settings_commands.get((owner, command.binding.action_key))
        if metadata is None or metadata[0] != digest:
            raise DuplicateEventError("Action key belongs to another native command")
        result = self._read(owner, receipt, command.kind)
        if settings_digest(result) != metadata[1]:
            raise StaleVersionError("Actual native settings changed; retain the historical receipt")
        return NativeWriteResult(receipt=receipt, result=result)

    def prepare(self, owner, command):
        command = PrepareSettingsReview.model_validate(command.model_dump())
        b, digest = command.binding, settings_digest(command)
        with self._state.lock, self._store.clinical.lock, self._transaction():
            prior = self._prior(owner, command, digest)
            if prior is not None:
                return prior
            task, _context, _values, snapshot = self._current(owner, b)
            if b.prepared_ref.id != b.action_key:
                raise ValidationError("Preparation marker must identify its owned action")
            old = (
                self._state.settings_preparations.get((owner, task.business_refs[0].id))
                if len(task.business_refs) == 1
                else None
            )
            stale = old is not None and (old[1] < task.revision or old[3] != self.revision(owner) or old[4] != snapshot)
            if not (task.state == "ready_for_review" or task.state == "awaiting_confirmation" and stale):
                raise StaleVersionError("Prepare a fresh current settings draft")
            if (owner, b.action_key) in self._state.actions:
                raise DuplicateEventError("Settings preparation cannot overwrite an existing action")
            self._state.actions[owner, b.action_key] = ActionReceipt(
                owner=owner,
                task_id=task.id,
                capability_id=task.capability_id,
                action_key=b.action_key,
                binding_revision=task.revision,
                state="succeeded",
                business_ref=b.prepared_ref,
                safe_reason="settings_prepared",
                clinical_revision=self._store.clinical.revisions.get(owner, 0),
                updated_at=self._clock.now(),
            )
            receipt = self._advance(owner, task, b, b.prepared_ref, True)
            self._state.settings_commands[owner, b.action_key] = digest, settings_digest(None)
            self._state.settings_preparations[owner, b.action_key] = (
                task.id,
                receipt.binding_revision,
                task.capability_id,
                self.revision(owner),
                snapshot,
            )
            return NativeWriteResult(receipt=receipt, result=None)

    def apply(self, owner, command):
        command = SETTINGS_WRITE_COMMAND.validate_python(settings_command_body(command))
        b, digest = command.binding, settings_digest(command)
        with self._state.lock, self._store.clinical.lock, self._transaction():
            prior = self._prior(owner, command, digest)
            if prior is not None:
                return prior
            task, context, values, snapshot = self._current(owner, b)
            if (
                b.capability_id not in CAPABILITIES[command.kind]
                or task.state != "awaiting_confirmation"
                or task.business_refs != (b.prepared_ref,)
            ):
                raise StaleVersionError("Confirm the exact current prepared settings operation")
            expected = task.id, task.revision, task.capability_id, self.revision(owner), snapshot
            if self._state.settings_preparations.get((owner, b.prepared_ref.id)) != expected:
                raise StaleVersionError("Technical settings preparation changed")
            payload = getattr(command, "values", None)
            target = (
                payload.id
                if command.kind in {"create_contact", "feedback"}
                else command.contact_id
                if command.kind in {"edit_contact", "delete_contact"}
                else None
            )
            self._adapters[task.capability_id].validate_payload(
                context, values, b.prepared_ref, target, payload, command.confirmed
            )
            if command.kind == "preferences":
                if command.previous != values.previous:
                    raise StaleVersionError("Confirm the actual previous preferences")
                result = self._preferences.save(owner, payload)
                ref = BusinessRef(kind="preference", id=owner)
            elif command.kind == "feedback":
                result = self._feedback.submit(owner, payload)
                ref = BusinessRef(kind="feedback", id=result.id)
            elif command.kind == "create_contact":
                result = self._contacts.create(owner, payload)
                ref = BusinessRef(kind="contact", id=result.id)
            else:
                if command.previous != values.previous or command.previous_updated_at != values.previous_updated_at:
                    raise StaleVersionError("Confirm the actual previous contact")
                result = (
                    self._contacts.update(owner, command.contact_id, payload)
                    if command.kind == "edit_contact"
                    else self._contacts.delete(owner, command.contact_id)
                )
                ref = BusinessRef(kind="contact", id=command.contact_id)
            receipt = self._advance(owner, task, b, ref, False)
            self._state.settings_commands[owner, b.action_key] = digest, settings_digest(result)
            return NativeWriteResult(receipt=receipt, result=result)

    def read(self, owner, command):
        command = SETTINGS_WRITE_COMMAND.validate_python(settings_command_body(command))
        with (self._state.lock, self._store.clinical.lock, self._preference_storage.local_transaction(),
              self._contact_storage.local_transaction(), self._feedback_storage.local_transaction()):
            result = self._prior(owner, command, settings_digest(command))
            if result is None:
                raise NotFoundError("Actual owned settings receipt unavailable")
            return result


class SupabaseSettingsWorkflowWrites:
    """Fixed owned metadata transactions, with no Auth or messaging capability."""

    def __init__(self, *, data, receipts):
        self._data, self._receipts = data, receipts

    def lookup(self, owner, action_key):
        self._data.check_patient(owner)
        return self._receipts.read_receipt(owner, action_key)

    def revision(self, owner):
        self._data.check_patient(owner)
        raw = self._data.request("POST", "/rest/v1/rpc/assistant_settings_revision", body={})
        if (
            not isinstance(raw, dict)
            or set(raw) != {"revision"}
            or type(raw["revision"]) is not int
            or raw["revision"] < 0
        ):
            raise ProviderUnavailableError("Current native settings revision unavailable")
        return raw["revision"]

    @staticmethod
    def _validate(owner, command, result, prior):
        b, row, r = command.binding, result.result, result.receipt
        if (
            r.owner != owner
            or r.task_id != b.task_id
            or r.action_key != b.action_key
            or r.capability_id != b.capability_id
            or r.binding_revision != b.task_revision + 1
            or prior is not None
            and r != prior
        ):
            raise ValueError
        if command.kind == "prepare_settings":
            if r.outcome != "prepared" or r.business_ref != b.prepared_ref or row is not None:
                raise ValueError
            return
        if r.outcome != "applied" or b.capability_id not in CAPABILITIES[command.kind]:
            raise ValueError
        if command.kind == "preferences":
            if (
                not isinstance(row, Preferences)
                or row.patient_id != owner
                or r.business_ref != BusinessRef(kind="preference", id=owner)
            ):
                raise ValueError
            changes = command.values.model_dump(exclude_none=True)
            if changes.get("text_scale_percent") is not None:
                changes["text_size"] = "large" if changes["text_scale_percent"] >= 125 else "standard"
            elif changes.get("text_size") is not None:
                changes["text_scale_percent"] = 125 if changes["text_size"] == "large" else 100
            if "preferred_language" in changes:
                changes["speech_locale"] = "zh-CN" if changes["preferred_language"] == "zh" else "en-SG"
            expected = command.previous.model_dump() | changes
            if any(getattr(row, key) != value for key, value in expected.items()):
                raise ValueError
        elif command.kind == "delete_contact":
            if row is not None or r.business_ref != BusinessRef(kind="contact", id=command.contact_id):
                raise ValueError
        else:
            target = command.contact_id if command.kind == "edit_contact" else command.values.id
            kind = "feedback" if command.kind == "feedback" else "contact"
            if (
                not isinstance(row, PatientFeedback if kind == "feedback" else CaregiverContact)
                or row.patient_id != owner
                or row.id != target
                or r.business_ref != BusinessRef(kind=kind, id=target)
                or any(getattr(row, key) != value for key, value in command.values.model_dump().items())
            ):
                raise ValueError

    def _request(self, owner, command, *, read_only=False):
        self._data.check_patient(owner)
        prior = self.lookup(owner, command.binding.action_key)
        if read_only and prior is None:
            raise NotFoundError("Actual owned settings receipt unavailable")
        endpoint = (
            "assistant_settings_read"
            if prior is not None
            else "assistant_settings_prepare"
            if command.kind == "prepare_settings"
            else "assistant_settings_write"
        )
        raw = self._data.request("POST", "/rest/v1/rpc/" + endpoint, body={"p_command": settings_command_body(command)})
        if isinstance(raw, dict) and set(raw) == {"error"}:
            errors = {
                "stale": StaleVersionError,
                "duplicate": DuplicateEventError,
                "not_found": NotFoundError,
                "invalid": ValidationError,
            }
            code = raw["error"] if isinstance(raw["error"], str) else "unavailable"
            raise errors.get(code, ProviderUnavailableError)(
                "Native settings outcome unavailable; inspect its actual receipt"
            )
        try:
            if not isinstance(raw, dict) or set(raw) != {"result", "replayed"} or type(raw["replayed"]) is not bool:
                raise ValueError
            result = NativeWriteResult[SettingsNativeResult].model_validate(raw["result"])
            self._validate(owner, command, result, prior)
            return result
        except (ValueError, TypeError, AttributeError):
            raise ProviderUnavailableError(
                "Native settings response differs from its owned confirmed command"
            ) from None

    def prepare(self, owner, command):
        self._data.check_patient(owner)
        return self._request(owner, PrepareSettingsReview.model_validate(command.model_dump()))

    def apply(self, owner, command):
        self._data.check_patient(owner)
        return self._request(owner, SETTINGS_WRITE_COMMAND.validate_python(settings_command_body(command)))

    def read(self, owner, command):
        self._data.check_patient(owner)
        return self._request(
            owner, SETTINGS_WRITE_COMMAND.validate_python(settings_command_body(command)), read_only=True
        )
