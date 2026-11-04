"""Actual local care transactions; persistent owner RPC is separately composed."""

import hashlib
import json
from contextlib import contextmanager
from copy import deepcopy

from ..contracts.assistant_workflows import BusinessRef, WorkflowContext, WorkflowUpdate, validate_workflow_values
from ..contracts.long_term import Barrier, CareTask, StockTransaction
from ..contracts.observations import Observation
from ..contracts.workflow_care_writes import (
    CARE_WRITE_COMMAND,
    CareNativeResult,
    LocalCareTransactionPort,
    LocalObservationTransactionPort,
    PrepareCareReview,
    care_command_payload,
)
from ..contracts.workflow_persistence import BusinessWriteReceipt, NativeWriteResult
from ..domain.errors import (
    DuplicateEventError,
    NotFoundError,
    ProviderUnavailableError,
    StaleVersionError,
    ValidationError,
)


class MemoryCareWorkflowWrites:
    def __init__(
        self,
        *,
        state,
        store,
        clock,
        tasks,
        controls,
        observations,
        observation_storage: LocalObservationTransactionPort,
        care,
        care_storage: LocalCareTransactionPort,
        adapter,
        preferences,
    ):
        self._state, self._store, self._clock = state, store, clock
        self._tasks, self._controls = tasks, controls
        self._observations, self._observation_storage = observations, observation_storage
        self._care, self._care_storage, self._adapter, self._preferences = care, care_storage, adapter, preferences

    def revision(self, owner):
        with self._store.clinical.lock, self._store.late_report_lock:
            return (
                self._store.clinical.revisions.get(owner, 0)
                + self._observation_storage.revision(owner)
                + self._care_storage.revision(owner)
                + sum(1 for patient, _key in self._store.events if patient == owner)
                + sum(1 for patient, _key in self._store.late_reports if patient == owner)
            )

    def lookup(self, owner, action_key):
        with self._state.lock:
            return self._state.business_receipts.get((owner, action_key))

    @contextmanager
    def _transaction(self):
        mappings = [
            self._state.tasks,
            self._state.controls,
            self._state.events,
            self._state.actions,
            self._state.business_receipts,
            self._state.care_commands,
            self._state.care_preparations,
            self._store.clinical.revisions,
        ]
        backups = [deepcopy(value) for value in mappings]
        used = set(self._state.used)
        with self._observation_storage.local_transaction(), self._care_storage.local_transaction():
            try:
                yield
            except BaseException:
                for current, old in zip(mappings, backups, strict=True):
                    current.clear()
                    current.update(old)
                self._state.used.clear()
                self._state.used.update(used)
                raise

    def _read_native(self, owner, command, receipt):
        ref = receipt.business_ref
        if command.kind == "delete_observation":
            if self._observations.get(owner, ref.id) is not None:
                raise StaleVersionError("Observation was recreated after the original deletion; retain its receipt")
            return NativeWriteResult(receipt=receipt, result=None)
        if command.kind == "save_observation":
            row = self._observations.get(owner, ref.id)
            expected = command.values.model_dump(exclude={"confirmed"})
            if row is None or any(getattr(row, key) != value for key, value in expected.items()):
                raise StaleVersionError("The applied observation changed or was deleted; retain its receipt")
        elif command.kind == "stock":
            row = next(
                (row for row in self._care_storage.stock(owner, command.medication_id) if row.id == ref.id), None
            )
        elif command.kind == "barrier":
            row = next((row for row in self._care.barriers(owner) if row.id == ref.id), None)
        else:
            row = next((row for row in self._care.tasks(owner) if row.id == ref.id), None)
            if row is not None and row.version != ref.version:
                raise StaleVersionError("The follow-up advanced; inspect its current record and retained receipt")
        if row is None:
            raise StaleVersionError("Applied native care record unavailable; retain its receipt")
        return NativeWriteResult(receipt=receipt, result=row)

    def prepare(self, owner, command):
        command = PrepareCareReview.model_validate(command.model_dump())
        b = command.binding
        digest = hashlib.sha256(
            json.dumps(command.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        with (
            self._state.lock,
            self._store.clinical.lock,
            self._store.late_report_lock,
            self._observation_storage.local_transaction(),
            self._care_storage.local_transaction(),
        ):
            prior = self.lookup(owner, b.action_key)
            if prior is not None:
                if self._state.care_commands.get((owner, b.action_key)) != digest:
                    raise DuplicateEventError("Preparation action belongs to different inputs")
                return NativeWriteResult(receipt=prior, result=None)
            task, control = self._tasks.get(owner, b.task_id), self._controls.get(owner, b.task_id)
            if (
                task.revision != b.task_revision
                or control.revision != b.task_revision
                or task.capability_id != b.capability_id
                or task.capability_id not in self._adapter.write_ids
                or control.mode != "allowed"
                or control.revoked
                or control.status != "idle"
                or task.save_mode != "allowed"
                or self.revision(owner) != b.expected_domain_revision
            ):
                raise StaleVersionError("The current independent care preparation changed")
            if b.run_binding is not None:
                self._state.require_durable_run(owner, b.run_binding, self._clock.now())
            preferences = self._preferences.get(owner)
            context = WorkflowContext(
                owner=owner,
                task_id=task.id,
                revision=task.revision,
                capability_id=task.capability_id,
                timezone=preferences.timezone,
                language=preferences.preferred_language,
            )
            values = validate_workflow_values(task.capability_id, task.fields)
            snapshot = self._adapter.review_snapshot(context, values)
            stale_marker = (
                len(task.business_refs) == 1
                and task.business_refs[0].kind == "care_review"
                and (old := self._state.care_preparations.get((owner, task.business_refs[0].id))) is not None
                and (old[1] < task.revision or old[3] != self.revision(owner) or old[4] != snapshot)
            )
            if not (task.state == "ready_for_review" or task.state == "awaiting_confirmation" and stale_marker):
                raise StaleVersionError("Prepare a fresh current care review after its inputs or native records change")
            with self._transaction():
                ref = self._adapter.prepare_once(context, values, (), b.action_key)
                if ref != b.prepared_ref:
                    raise StaleVersionError("Care preparation marker differs from this task")
                if b.run_binding is not None:
                    self._state.require_durable_run(owner, b.run_binding, self._clock.now())
                self._tasks.cas(
                    owner,
                    task.id,
                    task.revision,
                    b.action_key,
                    WorkflowUpdate(
                        state="awaiting_confirmation",
                        save_mode="allowed",
                        storage_state="saved",
                        fields=task.fields,
                        missing_fields=(),
                        attachment_ids=task.attachment_ids,
                        business_refs=(ref,),
                    ),
                )
                receipt = BusinessWriteReceipt(
                    owner=owner,
                    task_id=task.id,
                    action_key=b.action_key,
                    capability_id=task.capability_id,
                    binding_revision=task.revision + 1,
                    business_ref=ref,
                    domain_revision=self.revision(owner),
                    outcome="prepared",
                    recorded_at=self._clock.now(),
                )
                self._state.care_preparations[owner, ref.id] = (
                    task.id,
                    task.revision + 1,
                    task.capability_id,
                    receipt.domain_revision,
                    snapshot,
                )
                self._state.care_commands[owner, b.action_key] = digest
                self._state.business_receipts[owner, b.action_key] = receipt
                return NativeWriteResult(receipt=receipt, result=None)

    def apply(self, owner, command):
        command = CARE_WRITE_COMMAND.validate_python(care_command_payload(command))
        payload = care_command_payload(command)
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        b = command.binding
        key = (owner, b.action_key)
        with (
            self._state.lock,
            self._store.clinical.lock,
            self._store.late_report_lock,
            self._observation_storage.local_transaction(),
            self._care_storage.local_transaction(),
        ):
            prior = self.lookup(owner, b.action_key)
            if prior is not None:
                if self._state.care_commands.get(key) != digest:
                    raise DuplicateEventError("Care action already belongs to different patient inputs")
                return self._read_native(owner, command, prior)
            task, control = self._tasks.get(owner, b.task_id), self._controls.get(owner, b.task_id)
            capabilities = {
                "save_observation": {"observation.add", "observation.edit"},
                "delete_observation": {"observation.delete"},
                "stock": {"inventory.count"},
                "barrier": {"barrier.add"},
                "create_followup": {"followup.add"},
                "update_followup": {
                    "followup.edit",
                    "followup.contacted",
                    "followup.complete",
                    "followup.defer",
                    "followup.cancel",
                },
            }[command.kind]
            if (
                task.revision != b.task_revision
                or control.revision != b.task_revision
                or task.capability_id != b.capability_id
                or task.capability_id not in capabilities
                or task.state != "awaiting_confirmation"
                or control.status != "idle"
                or control.mode != "allowed"
                or control.revoked
                or task.save_mode != "allowed"
                or b.prepared_ref.kind != "care_review"
                or b.prepared_ref not in task.business_refs
                or self.revision(owner) != b.expected_domain_revision
            ):
                raise StaleVersionError("The current care records or independent patient review changed")
            if b.run_binding is not None:
                self._state.require_durable_run(owner, b.run_binding, self._clock.now())
            preference = self._preferences.get(owner)
            context = WorkflowContext(
                owner=owner,
                task_id=task.id,
                revision=task.revision,
                capability_id=task.capability_id,
                timezone=preference.timezone,
                language=preference.preferred_language,
            )
            values = validate_workflow_values(task.capability_id, task.fields)
            prepared = self._state.care_preparations.get((owner, b.prepared_ref.id))
            if (
                prepared is None
                or prepared[:4] != (task.id, task.revision, task.capability_id, self.revision(owner))
                or prepared[4] != self._adapter.review_snapshot(context, values)
            ):
                raise StaleVersionError("Prepare a fresh care review for these current native records")
            target = (
                command.observation_id
                if command.kind == "delete_observation"
                else command.values.id
                if command.kind == "save_observation"
                else command.medication_id
                if command.kind == "stock"
                else command.task_id
                if command.kind == "update_followup"
                else None
            )
            native_values = None if command.kind == "delete_observation" else command.values
            self._adapter.validate_current_request(context, values, b.prepared_ref, target, native_values)
            if command.kind == "update_followup":
                old = next((row for row in self._care.tasks(owner) if row.id == command.task_id), None)
                if old is None or old.version != command.expected_version:
                    raise StaleVersionError("Current linked follow-up version changed")
            with self._transaction():
                if command.kind == "save_observation":
                    native = self._observations.save(owner, command.values)
                    ref = BusinessRef(kind="observation", id=native.id)
                elif command.kind == "delete_observation":
                    self._observations.delete(owner, command.observation_id)
                    native = None
                    ref = BusinessRef(kind="observation", id=command.observation_id)
                elif command.kind == "stock":
                    actual = self._care.record_stock(owner, command.medication_id, command.values, preference.timezone)
                    native = next((row for row in actual.transactions if row.id == command.values.id), None)
                    if native is None:
                        raise StaleVersionError("Native stock transaction was not published")
                    ref = BusinessRef(kind="stock", id=native.id)
                elif command.kind == "barrier":
                    native = self._care.record_barrier(owner, command.values)
                    ref = BusinessRef(kind="barrier", id=native.id)
                elif command.kind == "create_followup":
                    native = self._care.create_task(owner, command.values)
                    ref = BusinessRef(kind="care_task", id=native.id, version=native.version)
                else:
                    native = self._care.update_task(owner, command.task_id, command.values)
                    ref = BusinessRef(kind="care_task", id=native.id, version=native.version)
                if b.run_binding is not None:
                    self._state.require_durable_run(owner, b.run_binding, self._clock.now())
                self._tasks.cas(
                    owner,
                    task.id,
                    task.revision,
                    b.action_key,
                    WorkflowUpdate(
                        state="completed",
                        save_mode="allowed",
                        storage_state="saved",
                        fields=task.fields,
                        missing_fields=(),
                        attachment_ids=task.attachment_ids,
                        business_refs=(ref,),
                    ),
                )
                receipt = BusinessWriteReceipt(
                    owner=owner,
                    task_id=task.id,
                    action_key=b.action_key,
                    capability_id=task.capability_id,
                    binding_revision=task.revision + 1,
                    business_ref=ref,
                    domain_revision=self.revision(owner),
                    outcome="applied",
                    recorded_at=self._clock.now(),
                )
                self._state.care_commands[key] = digest
                self._state.business_receipts[key] = receipt
                return NativeWriteResult(receipt=receipt, result=native)

    def read(self, owner, command):
        command = CARE_WRITE_COMMAND.validate_python(care_command_payload(command))
        digest = hashlib.sha256(
            json.dumps(care_command_payload(command), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        with (
            self._state.lock,
            self._store.clinical.lock,
            self._store.late_report_lock,
            self._observation_storage.local_transaction(),
            self._care_storage.local_transaction(),
        ):
            prior = self.lookup(owner, command.binding.action_key)
            if prior is None:
                raise NotFoundError("Actual owned care receipt unavailable")
            if self._state.care_commands.get((owner, command.binding.action_key)) != digest:
                raise DuplicateEventError("Care result belongs to different confirmed inputs")
            return self._read_native(owner, command, prior)


class SupabaseCareWorkflowWrites:
    """Owner-JWT fixed commands; receipt recovery never retries a native write."""

    def __init__(self, *, data, receipts):
        self._data, self._receipts = data, receipts

    def revision(self, owner):
        self._data.check_patient(owner)
        raw = self._data.request("POST", "/rest/v1/rpc/assistant_care_revision", body={})
        if (
            not isinstance(raw, dict)
            or set(raw) != {"revision"}
            or type(raw["revision"]) is not int
            or raw["revision"] < 0
        ):
            raise ProviderUnavailableError("Current care revision unavailable")
        return raw["revision"]

    def lookup(self, owner, action_key):
        self._data.check_patient(owner)
        return self._receipts.read_receipt(owner, action_key)

    def _request(self, owner, command, preparing, *, read_only=False):
        b = command.binding
        prior = self.lookup(owner, b.action_key)
        if read_only and prior is None:
            raise NotFoundError("Actual owned care receipt unavailable")
        endpoint = (
            "assistant_care_read"
            if prior is not None
            else ("assistant_care_prepare" if preparing else "assistant_care_write")
        )
        payload = command.model_dump(mode="json") if preparing else care_command_payload(command)
        raw = self._data.request("POST", "/rest/v1/rpc/" + endpoint, body={"p_command": payload})
        if (
            not isinstance(raw, dict)
            or set(raw) not in ({"result"}, {"result", "replayed"}, {"error"})
            or ("replayed" in raw and type(raw["replayed"]) is not bool)
        ):
            raise ProviderUnavailableError("Care outcome unavailable; inspect its receipt")
        if "error" in raw:
            errors = {
                "stale": StaleVersionError,
                "duplicate": DuplicateEventError,
                "invalid": ValidationError,
                "not_found": NotFoundError,
            }
            kind = raw["error"] if isinstance(raw["error"], str) else "unavailable"
            raise errors.get(kind, ProviderUnavailableError)("Care review changed; inspect its current record")
        try:
            result = NativeWriteResult[CareNativeResult].model_validate(raw["result"])
            receipt = result.receipt
            if (
                receipt.owner != owner
                or receipt.task_id != b.task_id
                or receipt.action_key != b.action_key
                or receipt.capability_id != b.capability_id
                or receipt.binding_revision != b.task_revision + 1
                or receipt.domain_revision < b.expected_domain_revision
                or receipt.outcome != ("prepared" if preparing else "applied")
                or (prior is not None and (receipt != prior or raw.get("replayed") is not True))
            ):
                raise ValueError
            if preparing:
                if receipt.business_ref != b.prepared_ref or result.result is not None:
                    raise ValueError
            else:
                self._validate_native(owner, command, result)
            return result
        except (ValueError, TypeError, AttributeError):
            raise ProviderUnavailableError("Care result binding unavailable; inspect its native receipt") from None

    @staticmethod
    def _validate_native(owner, command, result):
        row, ref = result.result, result.receipt.business_ref
        if command.kind == "delete_observation":
            if row is not None or ref != BusinessRef(kind="observation", id=command.observation_id):
                raise ValueError
            return
        model, kind = {
            "save_observation": (Observation, "observation"),
            "stock": (StockTransaction, "stock"),
            "barrier": (Barrier, "barrier"),
            "create_followup": (CareTask, "care_task"),
            "update_followup": (CareTask, "care_task"),
        }[command.kind]
        native_id = command.task_id if command.kind == "update_followup" else command.values.id
        version = (
            (command.expected_version + 1 if command.kind == "update_followup" else 1) if kind == "care_task" else None
        )
        if (
            not isinstance(row, model)
            or row.patient_id != owner
            or row.id != native_id
            or ref != BusinessRef(kind=kind, id=native_id, version=version)
        ):
            raise ValueError
        if command.kind == "stock" and row.medication_id != command.medication_id:
            raise ValueError
        if kind == "care_task" and (row.version != version or not any(e.id == command.values.id for e in row.history)):
            raise ValueError
        expected = command.values.model_dump(
            exclude={"confirmed", "historical_confirmed", "expected_version", "id"},
            exclude_unset=command.kind == "update_followup",
        )
        if kind == "care_task":
            if command.kind == "create_followup":
                expected["status"] = "open"
            if command.values.reminder_offsets is not None or (
                command.kind == "update_followup" and "reminder_offsets" in command.values.model_fields_set
            ):
                offsets = sorted(set(command.values.reminder_offsets or []), reverse=True)
                expected.update(reminder_offsets=offsets, reminder_minutes=max(offsets, default=None))
            elif command.kind == "update_followup" and "reminder_minutes" in expected:
                expected["reminder_offsets"] = None
            if command.kind == "update_followup" and expected.get("due_at") is None:
                expected.pop("due_at", None)
            if "reminder_offsets" in expected:
                desired_offsets = expected.pop("reminder_offsets")
                if desired_offsets is None:
                    minutes = expected.get("reminder_minutes", row.reminder_minutes)
                    desired_offsets = [] if minutes is None else [minutes]
                actual_offsets = row.reminder_offsets
                if actual_offsets is None:
                    actual_offsets = [] if row.reminder_minutes is None else [row.reminder_minutes]
                if desired_offsets != actual_offsets:
                    raise ValueError
        if any(getattr(row, name) != value for name, value in expected.items()):
            raise ValueError

    def prepare(self, owner, command):
        self._data.check_patient(owner)
        return self._request(owner, PrepareCareReview.model_validate(command.model_dump()), True)

    def apply(self, owner, command):
        self._data.check_patient(owner)
        return self._request(owner, CARE_WRITE_COMMAND.validate_python(care_command_payload(command)), False)

    def read(self, owner, command):
        self._data.check_patient(owner)
        return self._request(
            owner, CARE_WRITE_COMMAND.validate_python(care_command_payload(command)), False, read_only=True
        )
