"""Explicit memory/owner-JWT run control; never a remote mutable-lock facade."""

import hashlib
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID, uuid4

from ..application.agent_runtime_metadata import combine_usage
from ..contracts.agent_execution import (
    BudgetExceeded,
    DeadlineExceeded,
    RunEvent,
    RunMetadata,
    RunSnapshot,
    TaskCancelled,
)
from ..contracts.workflow_run_control import RUN_WORKER_COMMAND, RunControlState
from ..domain.errors import DuplicateEventError, NotFoundError, ProviderUnavailableError, StaleVersionError


class SupabaseDurableRunControl:
    def __init__(self, data):
        self._data = data

    def _call(self, owner, run_id, kind, *, task_id=None):
        self._data.check_patient(owner)
        command = {"kind": kind, "run_id": str(run_id)}
        if kind == "start":
            command["task_id"] = str(task_id) if task_id is not None else None
        raw = self._data.request(
            "POST", "/rest/v1/rpc/assistant_run_control", body={"p_command": command}, timeout_seconds=3
        )
        if not isinstance(raw, dict) or set(raw) not in ({"result"}, {"error"}):
            raise ProviderUnavailableError("Run control response unavailable")
        if "error" in raw:
            kinds = {"not_found": NotFoundError, "stale": StaleVersionError, "duplicate": DuplicateEventError}
            error = raw["error"]
            cls = kinds.get(error, ProviderUnavailableError) if isinstance(error, str) else ProviderUnavailableError
            raise cls("Run control changed; inspect its current state")
        try:
            state = RunControlState.model_validate(raw["result"])
            if state.owner != owner or state.run_id != run_id or (kind == "start" and state.task_id != task_id):
                raise ValueError
            return state
        except (ValueError, TypeError):
            raise ProviderUnavailableError("Run control response binding unavailable") from None

    def start(self, owner, run_id, task_id):
        return self._call(owner, run_id, "start", task_id=task_id)

    def read(self, owner, run_id):
        return self._call(owner, run_id, "read")

    def request_cancel(self, owner, run_id):
        return self._call(owner, run_id, "cancel")


@dataclass
class DurableMemoryRun:
    owner: UUID
    run_id: UUID
    task_id: UUID | None
    started_at: object
    deadline_at: object
    worker_ticket: UUID = field(default_factory=uuid4)
    worker_nonce: UUID = field(default_factory=uuid4)
    epoch: int = 0
    status: str = "running"
    metadata: RunMetadata | None = None
    events: list[RunEvent] = field(default_factory=list)
    operations: dict[UUID, str] = field(default_factory=dict)
    active_spans: dict[UUID, str] = field(default_factory=dict)
    attempts: dict[UUID, UUID] = field(default_factory=dict)
    responses: set[UUID] = field(default_factory=set)


class MemoryDurableRunControl:
    def __init__(self, *, clock, state):
        self._clock, self._state = clock, state

    @staticmethod
    def _event(row, kind, **values):
        row.events.append(
            RunEvent(
                sequence=len(row.events) + 1,
                run_id=row.run_id,
                task_id=row.task_id,
                kind=kind,
                status=row.status,
                **values,
            )
        )

    def _snapshot(self, row, *, acquired=False):
        return RunControlState(
            owner=row.owner,
            run_id=row.run_id,
            task_id=row.task_id,
            epoch=row.epoch,
            worker_ticket=row.worker_ticket,
            worker_nonce=row.worker_nonce,
            started_at=row.started_at,
            deadline_at=row.deadline_at,
            server_now=self._clock.now(),
            status=row.status,
            claim_acquired=acquired,
            snapshot=RunSnapshot(status=row.status, metadata=row.metadata, events=tuple(row.events)),
        )

    def _get(self, owner, run_id):
        row = self._state.durable_runs.get((owner, run_id))
        if row is None:
            raise NotFoundError("Assistant run not found")
        return row

    def start(self, owner, run_id, task_id):
        with self._state.lock:
            if (owner, run_id) in self._state.durable_runs:
                raise DuplicateEventError("Assistant run already exists; inspect its status")
            if task_id is not None and (owner, task_id) not in self._state.controls:
                raise NotFoundError("Owned workflow control required")
            now = self._clock.now()
            row = DurableMemoryRun(
                owner, run_id, task_id, now, now + timedelta(seconds=45), metadata=RunMetadata(run_id=run_id)
            )
            self._event(row, "run_started")
            self._state.durable_runs[(owner, run_id)] = row
            return self._snapshot(row)

    def read(self, owner, run_id):
        with self._state.lock:
            return self._snapshot(self._get(owner, run_id))

    def request_cancel(self, owner, run_id):
        with self._state.lock:
            row = self._get(owner, run_id)
            if row.status == "running":
                row.status = "cancelling"
                self._event(row, "run_cancelling", reason_key="cancelled")
            return self._snapshot(row)

    def _running(self, row):
        if row.status in {"cancelling", "cancelled"}:
            raise TaskCancelled()
        if row.status != "running":
            raise StaleVersionError("Assistant run is finished")
        if self._clock.now() >= row.deadline_at:
            raise DeadlineExceeded()

    def record_run(self, command, *, timeout_seconds):
        command = RUN_WORKER_COMMAND.validate_python(command)
        if timeout_seconds <= 0:
            raise ProviderUnavailableError("Run observation budget unavailable")
        with self._state.lock:
            row = next((r for r in self._state.durable_runs.values() if r.worker_ticket == command.ticket_id), None)
            if row is None or row.worker_nonce != command.nonce:
                raise NotFoundError("Run observation ticket unavailable")
            digest = hashlib.sha256(command.model_dump_json(exclude={"nonce"}).encode()).hexdigest()
            previous = row.operations.get(command.event_id)
            if previous is not None:
                if previous != digest:
                    raise DuplicateEventError("Run event identifier was reused")
                return self._snapshot(row)
            if command.kind == "claim":
                if row.epoch != 0:
                    raise DuplicateEventError("Assistant run already claimed; tool replay is forbidden")
                self._running(row)
                if command.epoch != 0:
                    raise StaleVersionError("Run claim epoch changed")
                row.epoch = 1
                row.metadata = row.metadata.model_copy(
                    update={"revision": command.revision, "runtime_hash": command.runtime_hash}
                )
                row.operations[command.event_id] = digest
                return self._snapshot(row, acquired=True)
            if command.epoch != row.epoch or (row.epoch == 0 and command.kind != "recover_interrupted"):
                raise StaleVersionError("Run worker epoch changed")
            self._apply(row, command)
            row.operations[command.event_id] = digest
            return self._snapshot(row)

    def _apply(self, row, command):
        if command.kind == "start_step":
            self._running(row)
            if command.span_id in row.active_spans:
                raise DuplicateEventError("Run step already started")
            if command.step_kind in {"model", "tool"}:
                name = "model_requests" if command.step_kind == "model" else "tool_calls"
                count = getattr(row.metadata, name)
                if count >= 4:
                    raise BudgetExceeded()
                row.metadata = row.metadata.model_copy(update={name: count + 1})
            row.active_spans[command.span_id] = command.step_kind
            self._event(row, "step_started", action_key=command.step_kind)
        elif command.kind == "finish_step":
            kind = row.active_spans.pop(command.span_id, None)
            if kind is None:
                raise StaleVersionError("Owned active run step required")
            self._event(
                row,
                "step_completed" if command.succeeded else "step_failed",
                action_key=kind,
                duration_ms=command.duration_ms,
            )
        elif command.kind == "record_usage":
            self._provider(row, command.observation)
        elif command.kind == "recover_interrupted":
            if self._clock.now() < row.deadline_at or row.status not in {"running", "cancelling"}:
                raise StaleVersionError("Run cannot be marked interrupted before its deadline")
            row.status = "failed"
            self._event(row, "run_failed", reason_key="worker_interrupted")
        elif command.kind == "finish":
            if row.status in {"completed", "cancelled", "failed"}:
                raise StaleVersionError("A terminal run cannot change state")
            if command.status == "completed":
                self._running(row)
                if row.active_spans:
                    raise StaleVersionError("Active steps cannot be declared complete")
            row.status = command.status
            row.metadata = row.metadata.model_copy(update={"duration_ms": command.duration_ms})
            self._event(
                row,
                {"completed": "run_completed", "cancelled": "run_cancelled", "failed": "run_failed"}[row.status],
                reason_key=command.reason,
            )

    def _provider(self, row, observation):
        if observation.phase == "metadata":
            self._running(row)
            row.metadata = row.metadata.model_copy(update=observation.model_dump(exclude={"phase"}))
        elif observation.phase == "attempt":
            self._running(row)
            if row.active_spans.get(observation.span_id) != "model":
                raise StaleVersionError("Owned model step required for SDK attempt")
            if observation.attempt_id in row.attempts:
                raise DuplicateEventError("SDK attempt already recorded")
            retry = observation.span_id in row.attempts.values()
            row.attempts[observation.attempt_id] = observation.span_id
            row.metadata = row.metadata.model_copy(
                update={
                    "provider": "gemini",
                    "sdk_attempts": (row.metadata.sdk_attempts or 0) + 1,
                    "sdk_retries": (row.metadata.sdk_retries or 0) + int(retry),
                }
            )
        else:
            if observation.attempt_id not in row.attempts:
                raise StaleVersionError("Observed SDK attempt required for returned metadata")
            if observation.attempt_id in row.responses:
                raise DuplicateEventError("SDK response already observed")
            changes = {"returned_model": observation.returned_model}
            if observation.usage is not None:
                changes.update(
                    usage=combine_usage(row.metadata.usage, observation.usage),
                    usage_responses=row.metadata.usage_responses + 1,
                )
            row.metadata = row.metadata.model_copy(update=changes)
            row.responses.add(observation.attempt_id)
