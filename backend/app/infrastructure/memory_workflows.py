"""Isolated in-process workflow storage. Never a persistent-environment fallback."""

import hashlib
from copy import deepcopy
from datetime import timedelta
from threading import RLock
from uuid import UUID

from ..contracts.agent_execution import RunRecord
from ..contracts.assistant_workflows import (
    ActionReceipt,
    ControlReceipt,
    SaveMode,
    WorkflowContext,
    WorkflowTask,
    WorkflowUpdate,
)
from ..contracts.ports import Clock
from ..contracts.workflow_attachments import CleanupReceipt, DeleteReceipt, OriginalAttachment, StoredObject
from ..contracts.workflow_persistence import BusinessWriteReceipt, parse_workflow_mutation
from ..domain.errors import DuplicateEventError, NotFoundError, StaleVersionError, ValidationError


class MemoryWorkflowState:
    """One explicitly injected memory transaction boundary for body/control ports."""

    def __init__(self):
        self.lock = RLock()
        self.runs: dict[tuple[UUID, UUID], RunRecord] = {}
        self.durable_runs: dict = {}
        self.tasks: dict[tuple[UUID, UUID], WorkflowTask] = {}
        self.events: dict[tuple[UUID, UUID, UUID], tuple[str | None, WorkflowTask]] = {}
        self.controls: dict[tuple[UUID, UUID], ControlReceipt] = {}
        self.used: set[tuple[UUID, UUID, UUID]] = set()
        self.actions: dict[tuple[UUID, UUID], ActionReceipt] = {}
        self.business_receipts: dict[tuple[UUID, UUID], BusinessWriteReceipt] = {}
        self.medication_commands: dict[tuple[UUID, UUID], str] = {}
        self.medication_result_refs: dict = {}
        self.record_commands: dict[tuple[UUID, UUID], str] = {}
        self.record_preparations: dict = {}
        self.care_commands: dict[tuple[UUID,UUID],str] = {}
        self.care_preparations: dict = {}
        self.media_commands: dict = {}
        self.media_preparations: dict = {}
        self.media_registration_duplicates: dict = {}
        self.media_original_links: dict = {}
        self.media_storage_tickets: dict = {}
        self.media_storage_verifications: dict = {}
        self.deleting_media_objects: set = set()
        self.media_delete_tickets: dict = {}
        self.media_delete_verifications: dict = {}
        self.media_cleanup_settlements: dict = {}
        self.settings_commands: dict = {}
        self.settings_preparations: dict = {}
        self.reminder_commands: dict = {}
        self.reminder_preparations: dict = {}
        self.originals: dict[tuple[UUID, UUID], OriginalAttachment] = {}
        self.original_objects: dict[tuple[UUID, str], bytes] = {}
        self.cleanup: dict[tuple[UUID, UUID], CleanupReceipt] = {}
        self.storage_tickets: dict = {}
        self.storage_verifications: dict = {}
        self.deleting_originals: set[tuple[UUID, UUID]] = set()

    def require_original_reference(self, owner, attachment_id):
        if (owner, attachment_id) in self.deleting_originals:
            raise StaleVersionError("Original deletion is pending or complete; this key cannot be reused")

    def require_durable_run(self, owner, binding, now):
        row = self.durable_runs.get((owner, binding.run_id))
        if (row is None or row.status != "running" or row.epoch != binding.epoch
                or now is None or now >= row.deadline_at):
            raise StaleVersionError("The bound run stopped, expired or changed")

    def suspend_foreground(self, owner, workspace_id, conversation_id, except_task, now):
        for key, control in tuple(self.controls.items()):
            if (
                control.owner == owner
                and control.conversation_id == conversation_id
                and (conversation_id is not None or control.workspace_id == workspace_id)
                and control.task_id != except_task
                and control.status not in {"suspended", "cancelled", "completed"}
            ):
                revision = control.revision + 1
                self.controls[key] = control.model_copy(
                    update={
                        "revision": revision,
                        "status": "suspended",
                        "processing_event_id": None,
                        "lease_until": None,
                    }
                )
                if key in self.tasks:
                    self.tasks[key] = self.tasks[key].model_copy(
                        update={
                            "revision": revision,
                            "state": "suspended",
                            "updated_at": now,
                        },
                        deep=True,
                    )


class MemoryWorkflowMutations:
    """Explicit memory transaction; no callback can escape the state boundary."""

    def __init__(self, clock: Clock, *, state: MemoryWorkflowState):
        self._state, self._clock = state, clock
        self._tasks = MemoryWorkflowRepository(clock, state=state)
        self._controls = MemoryControlRepository(clock, state=state)

    def task_receipts(self, owner, task_id):
        with self._state.lock:
            rows = tuple(r for r in self._state.business_receipts.values() if r.owner == owner and r.task_id == task_id)
            if len(rows) > 2000:
                raise ValidationError("Task receipt collection exceeds its bounded read")
            return tuple(sorted(rows, key=lambda r: (r.recorded_at, str(r.action_key))))

    def apply(self, owner, command):
        command = parse_workflow_mutation(command)
        with self._state.lock:
            if getattr(command, "run_binding", None) is not None:
                self._state.require_durable_run(owner, command.run_binding, self._clock.now())
            names = ("tasks", "events", "controls", "used", "originals", "cleanup")
            before = {name: deepcopy(getattr(self._state, name)) for name in names}
            try:
                return self._apply(owner, command)
            except Exception:
                # Keep the dictionaries themselves stable for already-injected repos.
                for name, values in before.items():
                    current = getattr(self._state, name)
                    current.clear()
                    current.update(values)
                raise

    @staticmethod
    def _update(task, state):
        return WorkflowUpdate(state=state, save_mode=task.save_mode, storage_state=task.storage_state,
                              fields=task.fields, missing_fields=task.missing_fields,
                              attachment_ids=task.attachment_ids, business_refs=task.business_refs)

    def _apply(self, owner, command):
        from ..contracts.assistant_workflows import validate_workflow_values

        if command.kind == "start":
            if command.task.owner != owner:
                raise ValidationError("Workflow belongs to another patient")
            validate_workflow_values(command.task.capability_id, command.task.fields)
            return self._tasks.create(command.task, suspend_foreground=True,
                                      event_id=command.event_id, request_digest=command.request_digest)
        if command.kind == "start_ephemeral":
            if command.control.owner != owner:
                raise ValidationError("Workflow belongs to another patient")
            return self._controls.create(command.control, suspend_foreground=True)
        if command.kind == "revoke":
            return self._controls.revoke(owner, command.task_id, command.expected_revision, command.event_id)
        if command.kind == "switch_mode":
            return self._controls.switch_mode(
                owner, command.task_id, command.expected_revision, command.event_id, command.mode
            )
        if command.kind == "bind_conversation":
            return self._tasks.bind_conversation(
                owner, command.task_id, command.expected_revision, command.conversation_id
            )
        if command.kind == "advance":
            current = self._tasks.get(owner, command.task_id)
            if command.update.state == "completed":
                raise ValidationError("Business completion requires a coupled result transaction")
            validate_workflow_values(current.capability_id, command.update.fields)
            return self._tasks.cas(owner, command.task_id, command.expected_revision, command.event_id,
                                   command.update, command.request_digest)
        source, target = self._tasks.get(owner, command.task_id), self._tasks.get(owner, command.target_task_id)
        for row, revision in [(source, command.expected_revision), (target, command.target_revision)]:
            control = self._controls.get(owner, row.id)
            if (row.revision != revision or control.revision != revision or control.mode != "allowed"
                    or control.revoked or control.processing_event_id is not None
                    or row.state in {"completed", "cancelled"}):
                raise StaleVersionError("Both recovery tasks must have current saved versions")
        self._tasks.cas(owner, source.id, source.revision, command.event_id, self._update(source, "suspended"))
        return self._tasks.cas(
            owner, target.id, target.revision, command.event_id, self._update(target, command.target_state)
        )

    def read_receipt(self, owner, action_key):
        # Domain ports will publish coupled receipts. Legacy ActionReceipt is not
        # interchangeable with one and must never be upgraded by this repository.
        with self._state.lock:
            row = self._state.business_receipts.get((owner, action_key))
            return row.model_copy(deep=True) if row is not None else None


class MemoryWorkflowRepository:
    def __init__(self, clock: Clock, *, state: MemoryWorkflowState | None = None):
        self._clock = clock
        self._state = state if state is not None else MemoryWorkflowState()
        self._tasks, self._events, self._lock = self._state.tasks, self._state.events, self._state.lock

    def bind_conversation(self, owner, task_id, expected_revision, conversation_id) -> WorkflowTask:
        with self._lock:
            task = self.get(owner, task_id)
            control = self._state.controls[(owner, task_id)]
            if (
                task.revision != expected_revision
                or control.revision != expected_revision
                or control.mode != "allowed"
                or control.revoked
            ):
                raise StaleVersionError("Workflow changed before conversation binding")
            if task.conversation_id not in {None, conversation_id}:
                raise ValidationError("Workflow belongs to another conversation")
            if task.conversation_id == conversation_id:
                return task
            if control.processing_event_id is not None:
                raise StaleVersionError("Workflow has a processing or interrupted request")
            if task.state not in {"suspended", "cancelled", "completed"}:
                self._state.suspend_foreground(owner, task.workspace_id, conversation_id, task_id, self._clock.now())
            task = task.model_copy(
                update={
                    "conversation_id": conversation_id,
                    "revision": task.revision + 1,
                    "updated_at": self._clock.now(),
                }
            )
            self._tasks[(owner, task_id)] = task
            self._state.controls[(owner, task_id)] = control.model_copy(
                update={
                    "conversation_id": conversation_id,
                    "revision": task.revision,
                }
            )
            return task.model_copy(deep=True)

    def create(
        self,
        task: WorkflowTask,
        *,
        suspend_foreground: bool = False,
        event_id: UUID | None = None,
        request_digest: str | None = None,
    ) -> WorkflowTask:
        with self._lock:
            for attachment_id in task.attachment_ids:
                self._state.require_original_reference(task.owner, attachment_id)
            for reference in task.business_refs:
                if reference.kind == "file":
                    self._state.require_original_reference(task.owner, reference.id)
            key = (task.owner, task.id)
            if key in self._tasks:
                if event_id is not None and request_digest is not None:
                    replay = self.event_result(task.owner, task.id, event_id, request_digest)
                    if replay is not None:
                        return replay
                raise ValidationError("Workflow already exists")
            control = self._state.controls.get(key)
            if control is not None and (
                control.mode != "allowed" or control.revoked or control.revision != task.revision
            ):
                raise StaleVersionError("Workflow saving permission changed")
            if suspend_foreground:
                self._state.suspend_foreground(
                    task.owner, task.workspace_id, task.conversation_id, task.id, self._clock.now()
                )
            self._state.controls[key] = ControlReceipt(
                owner=task.owner,
                task_id=task.id,
                capability_id=task.capability_id,
                workspace_id=task.workspace_id,
                conversation_id=task.conversation_id,
                revision=task.revision,
                mode=task.save_mode,
            )
            self._tasks[key] = task.model_copy(deep=True)
            if event_id is not None:
                self._events[(task.owner, task.id, event_id)] = (request_digest, task.model_copy(deep=True))
                self._state.used.add((task.owner, task.id, event_id))
            return task.model_copy(deep=True)

    def get(self, owner: UUID, task_id: UUID) -> WorkflowTask:
        with self._lock:
            row = self._tasks.get((owner, task_id))
            if row is None:
                raise NotFoundError("Workflow not found for this patient")
            return row.model_copy(deep=True)

    def cas(
        self,
        owner: UUID,
        task_id: UUID,
        expected_revision: int,
        event_id: UUID,
        update: WorkflowUpdate,
        request_digest: str | None = None,
    ) -> WorkflowTask:
        with self._lock:
            for attachment_id in update.attachment_ids:
                self._state.require_original_reference(owner, attachment_id)
            for reference in update.business_refs:
                if reference.kind == "file":
                    self._state.require_original_reference(owner, reference.id)
            row = self.get(owner, task_id)
            key = (owner, task_id, event_id)
            if key in self._events:
                saved_digest, saved_task = self._events[key]
                if request_digest is not None and saved_digest == request_digest:
                    return saved_task.model_copy(deep=True)
                raise DuplicateEventError("Workflow event already processed")
            if row.revision != expected_revision:
                raise StaleVersionError("Workflow changed; refresh it before continuing")
            control = self._state.controls[(owner, task_id)]
            if control.revision != expected_revision or control.mode != "allowed" or control.revoked:
                raise StaleVersionError("Workflow saving permission changed")
            if control.processing_event_id is not None and (
                control.processing_event_id != event_id
                or control.lease_until is None
                or control.lease_until <= self._clock.now()
            ):
                raise StaleVersionError("Workflow has an active or interrupted operation")
            updated = WorkflowTask.model_validate(
                {
                    **row.model_dump(mode="python"),
                    **update.model_dump(mode="python"),
                    "revision": row.revision + 1,
                    "updated_at": self._clock.now(),
                }
            )
            if updated.state not in {"suspended", "cancelled", "completed"}:
                self._state.suspend_foreground(owner, row.workspace_id, row.conversation_id, task_id, self._clock.now())
            self._tasks[(owner, task_id)] = updated.model_copy(deep=True)
            self._events[key] = (request_digest, updated.model_copy(deep=True))
            status = updated.state if updated.state in {"suspended", "cancelled", "completed"} else "idle"
            self._state.controls[(owner, task_id)] = control.model_copy(
                update={
                    "revision": updated.revision,
                    "status": status,
                    "processing_event_id": None,
                    "lease_until": None,
                }
            )
            self._state.used.add(key)
            return updated.model_copy(deep=True)

    def event_result(self, owner: UUID, task_id: UUID, event_id: UUID, request_digest: str) -> WorkflowTask | None:
        with self._lock:
            self.get(owner, task_id)
            saved = self._events.get((owner, task_id, event_id))
            if saved is None:
                return None
            if saved[0] != request_digest:
                raise DuplicateEventError("Workflow event ID was reused for different input")
            return saved[1].model_copy(deep=True)

    def list(self, owner: UUID, workspace_id: UUID | None = None) -> tuple[WorkflowTask, ...]:
        with self._lock:
            return tuple(
                row.model_copy(deep=True)
                for (patient, _), row in self._tasks.items()
                if patient == owner and (workspace_id is None or row.workspace_id == workspace_id)
            )

    def persistence_snapshot(self, owner: UUID) -> dict[str, object]:
        with self._lock:
            return {
                "tasks": [row.model_dump(mode="json") for row in self.list(owner)],
                "controls": [
                    row.model_dump(mode="json") for row in self._state.controls.values() if row.owner == owner
                ],
                "event_results": [
                    {"digest": digest, "task": task.model_dump(mode="json")}
                    for (patient, _, _), (digest, task) in self._events.items()
                    if patient == owner
                ],
            }


class MemoryActionRepository:
    def __init__(self, clock: Clock, *, state: MemoryWorkflowState | None = None):
        self._state = state if state is not None else MemoryWorkflowState()
        self._clock, self._lock, self._receipts = clock, self._state.lock, self._state.actions

    @staticmethod
    def _bound(context: WorkflowContext, receipt: ActionReceipt) -> None:
        if (
            receipt.owner != context.owner
            or receipt.task_id != context.task_id
            or receipt.capability_id != context.capability_id
        ):
            raise ValidationError("Operation belongs to another workflow")
        if receipt.binding_revision != context.revision:
            raise StaleVersionError("Operation belongs to another workflow revision")

    def reserve(self, context: WorkflowContext, action_key: UUID) -> ActionReceipt:
        with self._lock:
            key = (context.owner, action_key)
            existing = self._receipts.get(key)
            if existing is not None:
                self._bound(context, existing)
                return existing.model_copy(deep=True)
            receipt = ActionReceipt(
                action_key=action_key,
                owner=context.owner,
                task_id=context.task_id,
                capability_id=context.capability_id,
                binding_revision=context.revision,
                state="pending",
                updated_at=self._clock.now(),
            )
            self._receipts[key] = receipt
            return receipt.model_copy(deep=True)

    def complete(self, context: WorkflowContext, receipt: ActionReceipt) -> None:
        with self._lock:
            existing = self.read(context.owner, receipt.action_key)
            self._bound(context, existing)
            self._bound(context, receipt)
            if existing.business_ref is not None and existing.business_ref != receipt.business_ref:
                raise DuplicateEventError("Operation result reference cannot change")
            if existing.clinical_revision is not None and existing.clinical_revision != receipt.clinical_revision:
                raise DuplicateEventError("Operation clinical revision cannot change")
            if existing.state in {"succeeded", "failed"} and existing.state != receipt.state:
                raise DuplicateEventError("A completed operation cannot be replayed or downgraded")
            if existing.state == "outcome_unknown" and receipt.state == "pending":
                raise DuplicateEventError("An unknown operation must be observed before retrying")
            self._receipts[(context.owner, receipt.action_key)] = receipt.model_copy(deep=True)

    def read(self, owner: UUID, action_key: UUID) -> ActionReceipt:
        with self._lock:
            receipt = self._receipts.get((owner, action_key))
            if receipt is None:
                raise NotFoundError("Operation not found for this patient")
            return receipt.model_copy(deep=True)

    def list(self, owner: UUID, task_id: UUID) -> tuple[ActionReceipt, ...]:
        with self._lock:
            return tuple(
                row.model_copy(deep=True)
                for row in self._receipts.values()
                if row.owner == owner and row.task_id == task_id
            )


class MemoryControlRepository:
    """Content-free CAS/lease metadata; no request bodies or content hashes."""

    def __init__(self, clock: Clock, *, state: MemoryWorkflowState | None = None):
        self._state = state if state is not None else MemoryWorkflowState()
        self._clock, self._lock = clock, self._state.lock
        self._rows, self._used = self._state.controls, self._state.used

    def guarded_write(self, owner, task_id, revision, write) -> bool:
        with self._lock:
            control = self.get(owner, task_id)
            if control.mode != "allowed" or control.revoked or control.revision != revision:
                return False
            write()
            return True

    def create(self, receipt: ControlReceipt, *, suspend_foreground: bool = False) -> ControlReceipt:
        with self._lock:
            key = (receipt.owner, receipt.task_id)
            if key in self._rows:
                raise ValidationError("Workflow controls already exist")
            if suspend_foreground:
                self._state.suspend_foreground(
                    receipt.owner, receipt.workspace_id, receipt.conversation_id, receipt.task_id, self._clock.now()
                )
            self._rows[key] = receipt.model_copy(deep=True)
            return receipt.model_copy(deep=True)

    def get(self, owner: UUID, task_id: UUID) -> ControlReceipt:
        with self._lock:
            row = self._rows.get((owner, task_id))
            if row is None:
                raise NotFoundError("Workflow controls not found for this patient")
            if (
                row.processing_event_id is not None
                and row.lease_until is not None
                and row.lease_until <= self._clock.now()
            ):
                return row.model_copy(update={"status": "interrupted"}, deep=True)
            return row.model_copy(deep=True)

    def list(self, owner: UUID) -> tuple[ControlReceipt, ...]:
        with self._lock:
            return tuple(self.get(owner, row.task_id) for row in self._rows.values() if row.owner == owner)

    def claim(
        self,
        owner: UUID,
        task_id: UUID,
        expected_revision: int,
        event_id: UUID,
        capability_id: str,
        mode: SaveMode,
    ) -> ControlReceipt:
        with self._lock:
            row = self.get(owner, task_id)
            if row.revision != expected_revision:
                raise StaleVersionError("Workflow controls changed; refresh before continuing")
            if row.capability_id != capability_id or row.mode != mode:
                raise ValidationError("Workflow control binding does not match")
            if row.status in {"cancelled", "completed"}:
                raise ValidationError("Workflow is finished")
            if (owner, task_id, event_id) in self._used:
                raise DuplicateEventError("Workflow event already claimed")
            if row.processing_event_id is not None:
                if row.lease_until is not None and row.lease_until <= self._clock.now():
                    raise StaleVersionError("Workflow lease expired; observe its outcome before retrying")
                raise ValidationError("Another workflow event is processing")
            claimed = row.model_copy(
                update={
                    "processing_event_id": event_id,
                    "lease_until": self._clock.now() + timedelta(seconds=45),
                    "status": "processing",
                }
            )
            self._rows[(owner, task_id)] = claimed
            self._used.add((owner, task_id, event_id))
            return claimed.model_copy(deep=True)

    def finish(
        self,
        owner: UUID,
        task_id: UUID,
        expected_revision: int,
        event_id: UUID,
        *,
        status: str = "idle",
    ) -> ControlReceipt:
        with self._lock:
            row = self.get(owner, task_id)
            if (
                row.revision != expected_revision
                or row.processing_event_id != event_id
                or row.lease_until is None
                or row.lease_until <= self._clock.now()
            ):
                raise StaleVersionError("Workflow claim is stale or interrupted")
            finished = row.model_copy(
                update={
                    "revision": row.revision + 1,
                    "processing_event_id": None,
                    "lease_until": None,
                    "status": status,
                }
            )
            if status == "idle":
                self._state.suspend_foreground(owner, row.workspace_id, row.conversation_id, task_id, self._clock.now())
            self._rows[(owner, task_id)] = finished
            return finished.model_copy(deep=True)

    def revoke(
        self,
        owner: UUID,
        task_id: UUID,
        expected_revision: int,
        event_id: UUID | None = None,
    ) -> ControlReceipt:
        with self._lock:
            row = self.get(owner, task_id)
            if row.revision != expected_revision:
                raise StaleVersionError("Workflow controls changed before revocation")
            if event_id is not None:
                if (owner, task_id, event_id) in self._used:
                    raise DuplicateEventError("Workflow event already claimed")
                self._used.add((owner, task_id, event_id))
            revoked = row.model_copy(
                update={
                    "revision": row.revision + 1,
                    "mode": "ephemeral",
                    "revoked": True,
                    "processing_event_id": None,
                    "lease_until": None,
                    "status": row.status if row.status in {"suspended", "cancelled", "completed"} else "idle",
                }
            )
            self._rows[(owner, task_id)] = revoked
            self._state.tasks.pop((owner, task_id), None)
            for key in tuple(self._state.events):
                if key[:2] == (owner, task_id):
                    del self._state.events[key]
            for key, original in tuple(self._state.originals.items()):
                if original.owner == owner and original.task_id == task_id:
                    self._state.cleanup[key] = CleanupReceipt(
                        id=original.id,
                        owner=owner,
                        task_id=task_id,
                        object_ref=original.object_ref,
                        content_type=original.content_type,
                        source_ref=original.source_ref,
                        writer_pending=bool(original.pending_writer_ids) or not original.object_written,
                        pending_writer_ids=original.pending_writer_ids,
                        multiple_writers=original.multiple_writers,
                        reason="upload_inflight"
                        if original.pending_writer_ids or not original.object_written
                        else None,
                    )
                    del self._state.originals[key]
            return revoked.model_copy(deep=True)

    def switch_mode(self, owner, task_id, expected_revision, event_id, mode: SaveMode) -> ControlReceipt:
        if mode == "ephemeral":
            return self.revoke(owner, task_id, expected_revision, event_id)
        with self._lock:
            row = self.get(owner, task_id)
            if row.revision != expected_revision:
                raise StaleVersionError("Workflow controls changed before saving")
            if (owner, task_id, event_id) in self._used:
                raise DuplicateEventError("Workflow event already claimed")
            if row.status in {"processing", "interrupted", "cancelled", "completed"}:
                raise ValidationError("Resolve the current workflow state before saving")
            switched = row.model_copy(update={"mode": "allowed", "revoked": False, "revision": row.revision + 1})
            self._rows[(owner, task_id)] = switched
            self._used.add((owner, task_id, event_id))
            return switched.model_copy(deep=True)

    def recover(self, owner, task_id, expected_revision, event_id) -> ControlReceipt:
        with self._lock:
            row = self.get(owner, task_id)
            if row.revision != expected_revision or row.status != "interrupted":
                raise StaleVersionError("Workflow is not an interrupted claim at this revision")
            if (owner, task_id, event_id) in self._used:
                raise DuplicateEventError("Workflow event already claimed")
            recovered = row.model_copy(
                update={
                    "revision": row.revision + 1,
                    "status": "idle",
                    "processing_event_id": None,
                    "lease_until": None,
                }
            )
            self._rows[(owner, task_id)] = recovered
            self._used.add((owner, task_id, event_id))
            if (owner, task_id) in self._state.tasks:
                task = self._state.tasks[(owner, task_id)]
                self._state.tasks[(owner, task_id)] = task.model_copy(
                    update={
                        "revision": recovered.revision,
                        "state": "outcome_unknown",
                        "updated_at": self._clock.now(),
                    }
                )
            return recovered.model_copy(deep=True)


class MemoryOriginalRepository:
    def __init__(self, *, state: MemoryWorkflowState, tasks, controls):
        self._state, self._tasks, self._controls = state, tasks, controls

    def retry_reservation(self, context, attachment_id, event_id, *, starts_writer=True):
        with self._state.lock:
            row = self.get(context.owner, context.task_id, attachment_id)
            task = self._tasks.get(context.owner, context.task_id)
            if (
                row.state != "reserved"
                or task.state in {"completed", "cancelled"}
                or task.capability_id != context.capability_id
            ):
                raise ValidationError("This original cannot be retried")
            if starts_writer and len(row.pending_writer_ids) >= 64:
                raise ValidationError("Resolve the outstanding original write attempts before retrying")
            self._controls.claim(
                context.owner, context.task_id, context.revision, event_id, context.capability_id, "allowed"
            )
            updated = row.model_copy(
                update={
                    "binding_revision": context.revision,
                    "operation_event_id": event_id,
                    "pending_writer_ids": tuple(dict.fromkeys((*row.pending_writer_ids, event_id)))
                    if starts_writer
                    else row.pending_writer_ids,
                    "multiple_writers": row.multiple_writers or (starts_writer and bool(row.pending_writer_ids)),
                }
            )
            self._state.originals[(context.owner, attachment_id)] = updated
            return updated.model_copy(deep=True)

    def begin_extraction(self, context, attachment_id, event_id):
        with self._state.lock:
            row = self.get(context.owner, context.task_id, attachment_id)
            if row.state != "saved":
                raise ValidationError("Save the original before recognition")
            self._controls.claim(
                context.owner, context.task_id, context.revision, event_id, context.capability_id, "allowed"
            )
            updated = row.model_copy(
                update={"operation_event_id": event_id, "extraction_status": "pending", "reason": None}
            )
            self._state.originals[(context.owner, attachment_id)] = updated
            return updated.model_copy(deep=True)

    def note_written(self, owner, task_id, attachment_id, writer_id=None):
        with self._state.lock:
            row = self._state.originals.get((owner, attachment_id))
            if row is None:
                return False
            if row.task_id != task_id:
                raise NotFoundError("Original belongs to another task")
            remaining = (
                tuple(item for item in row.pending_writer_ids if item != writer_id)
                if writer_id
                else row.pending_writer_ids
                if row.multiple_writers
                else ()
            )
            self._state.originals[(owner, attachment_id)] = row.model_copy(
                update={"object_written": True, "pending_writer_ids": remaining}
            )
            return True

    def protect_source(self, context, attachment_id, source_ref, event_id):
        with self._state.lock:
            self._state.require_original_reference(context.owner, attachment_id)
            original = self.get(context.owner, context.task_id, attachment_id)
            if original.source_ref is not None and original.source_ref != source_ref:
                raise DuplicateEventError("A reviewed source association cannot be replaced")
            task = self._tasks.get(context.owner, context.task_id)
            self._controls.claim(
                context.owner, context.task_id, context.revision, event_id, context.capability_id, "allowed"
            )
            return self._commit(
                context, original.model_copy(update={"source_ref": source_ref}), event_id, state=task.state
            )

    def find_upload(self, owner, task_id, upload_id):
        with self._state.lock:
            return next(
                (
                    row.model_copy(deep=True)
                    for row in self._state.originals.values()
                    if row.owner == owner and row.task_id == task_id and row.upload_id == upload_id
                ),
                None,
            )

    def get(self, owner, task_id, attachment_id):
        with self._state.lock:
            row = self._state.originals.get((owner, attachment_id))
            if row is None or row.task_id != task_id:
                raise NotFoundError("Original not found for this patient and task")
            return row.model_copy(deep=True)

    def list(self, owner, task_id=None):
        with self._state.lock:
            return tuple(
                row.model_copy(deep=True)
                for row in self._state.originals.values()
                if row.owner == owner and (task_id is None or row.task_id == task_id)
            )

    def reserve(self, context, attachment):
        with self._state.lock:
            self._state.require_original_reference(context.owner, attachment.id)
            task = self._tasks.get(context.owner, context.task_id)
            if task.capability_id != context.capability_id or task.state in {"completed", "cancelled"}:
                raise ValidationError("This workflow cannot accept an original")
            if len(task.attachment_ids) >= 10:
                raise ValidationError("This workflow already has the maximum number of originals")
            if (attachment.owner, attachment.task_id, attachment.binding_revision) != (
                context.owner,
                context.task_id,
                context.revision,
            ):
                raise ValidationError("Original binding does not match the workflow")
            if self.find_upload(context.owner, context.task_id, attachment.upload_id) is not None:
                raise DuplicateEventError("Original upload was already reserved")
            self._controls.claim(
                context.owner, context.task_id, context.revision, attachment.upload_id, context.capability_id, "allowed"
            )
            # This intent, including the random object ref, exists before object I/O.
            reserved = attachment.model_copy(
                update={"operation_event_id": attachment.upload_id, "pending_writer_ids": (attachment.upload_id,)},
                deep=True,
            )
            self._state.originals[(context.owner, attachment.id)] = reserved
            return reserved.model_copy(deep=True)

    def _commit(self, context, attachment, event_id, *, state):
        self._state.require_original_reference(context.owner, attachment.id)
        task = self._tasks.get(context.owner, context.task_id)
        current = self.get(context.owner, context.task_id, attachment.id)
        attachment = attachment.model_copy(
            update={
                "object_written": current.object_written,
                "pending_writer_ids": current.pending_writer_ids,
                "multiple_writers": current.multiple_writers,
            }
        )
        self._tasks.cas(
            context.owner,
            context.task_id,
            context.revision,
            event_id,
            WorkflowUpdate(
                state=task.state if task.business_refs else state,
                save_mode="allowed",
                storage_state="saved",
                fields=task.fields,
                missing_fields=tuple(field for field in task.missing_fields if field != "source_image"),
                attachment_ids=tuple(dict.fromkeys((*task.attachment_ids, attachment.id))),
                business_refs=task.business_refs,
            ),
            request_digest=f"{attachment.original_checksum}:{attachment.source_kind}",
        )
        self._state.originals[(context.owner, attachment.id)] = attachment.model_copy(deep=True)
        return attachment.model_copy(deep=True)

    def publish(self, context, attachment, *, event_id=None):
        with self._state.lock:
            existing = self.get(context.owner, context.task_id, attachment.id)
            return self._commit(
                context,
                attachment.model_copy(update={"state": "saved", "object_written": existing.object_written}),
                event_id or attachment.upload_id,
                state="collecting",
            )

    def finish_extraction(self, context, attachment, event_id):
        with self._state.lock:
            self.get(context.owner, context.task_id, attachment.id)
            return self._commit(
                context,
                attachment,
                event_id,
                state="failed_recoverable"
                if attachment.extraction_status in {"failed", "interrupted"}
                else "collecting",
            )


class MemoryCleanupRepository:
    def __init__(self, *, state: MemoryWorkflowState):
        self._state = state

    def get(self, owner, attachment_id):
        with self._state.lock:
            row = self._state.cleanup.get((owner, attachment_id))
            if row is None:
                raise NotFoundError("Cleanup receipt not found for this patient")
            return row.model_copy(deep=True)

    def list(self, owner, task_id):
        with self._state.lock:
            return tuple(
                row.model_copy(deep=True)
                for row in self._state.cleanup.values()
                if row.owner == owner and row.task_id == task_id
            )

    def mark_written(self, owner, task_id, attachment_id, writer_id=None):
        with self._state.lock:
            row = self.get(owner, attachment_id)
            if row.task_id != task_id:
                raise NotFoundError("Cleanup belongs to another task")
            remaining = (
                tuple(item for item in row.pending_writer_ids if item != writer_id)
                if writer_id
                else row.pending_writer_ids
                if row.multiple_writers
                else ()
            )
            self._state.cleanup[(owner, attachment_id)] = row.model_copy(
                update={
                    "writer_pending": bool(remaining),
                    "pending_writer_ids": remaining,
                    "state": "pending",
                    "reason": None,
                }
            )

    def update(self, receipt):
        with self._state.lock:
            row = self.get(receipt.owner, receipt.id)
            if (row.task_id, row.object_ref) != (receipt.task_id, receipt.object_ref):
                raise ValidationError("Cleanup reference cannot be changed")
            updates = {
                "writer_pending": row.writer_pending,
                "pending_writer_ids": row.pending_writer_ids,
                "multiple_writers": row.multiple_writers,
            }
            if receipt.state == "deleted" and row.writer_pending:
                updates.update(state="pending", reason="upload_inflight")
            self._state.cleanup[(receipt.owner, receipt.id)] = receipt.model_copy(update=updates, deep=True)


class MemoryWorkflowObjects:
    def __init__(self, *, state: MemoryWorkflowState):
        self._state = state

    @staticmethod
    def _check(owner, key):
        parts = key.split("/")
        if len(parts) != 4 or parts[:2] != [str(owner), "workflow-originals"]:
            raise ValidationError("Invalid private original reference")
        try:
            UUID(parts[2])
            UUID(parts[3])
        except ValueError:
            raise ValidationError("Invalid private original reference") from None

    def put_original(self, owner, task_id, upload_id, content, content_type, *, object_ref):
        self._check(owner, object_ref)
        if object_ref.split("/")[2] != str(task_id):
            raise ValidationError("Original reference belongs to another task")
        with self._state.lock:
            self._state.require_original_reference(owner, UUID(object_ref.split('/')[3]))
            key = (owner, object_ref)
            if key in self._state.original_objects and self._state.original_objects[key] != content:
                raise DuplicateEventError("An immutable original cannot be overwritten")
            self._state.original_objects[key] = bytes(content)
            return StoredObject(
                object_ref=object_ref, checksum=hashlib.sha256(content).hexdigest(), byte_size=len(content)
            )

    def read(self, owner, key):
        self._check(owner, key)
        with self._state.lock:
            if (owner, key) not in self._state.original_objects:
                raise NotFoundError("Original object unavailable")
            return self._state.original_objects[(owner, key)]

    def delete(self, owner, key):
        self._check(owner, key)
        with self._state.lock:
            self._state.original_objects.pop((owner, key), None)
            return DeleteReceipt(state="deleted")
