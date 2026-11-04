"""Command-based execution; SQL owner/run fences guard actual persisted writes."""

from contextlib import contextmanager
from uuid import uuid4

from ..contracts.agent_execution import (
    DeadlineExceeded,
    ExecutionStopped,
    TaskCancelled,
    current_execution,
    execution_step,
)
from ..contracts.workflow_persistence import RunWriteBinding
from ..contracts.workflow_run_control import (
    ClaimRun,
    FinishRun,
    FinishRunStep,
    RecordRunProvider,
    RecoverInterruptedRun,
    StartRunStep,
)
from ..domain.errors import DuplicateEventError, ProviderUnavailableError, StaleVersionError
from .agent_runtime_metadata import content_hash, model_name


class DurableExecutionControl:
    def __init__(self, *, control, verifier, owner, state, monotonic):
        self._control, self._verifier, self._owner = control, verifier, owner
        self._state, self._now, self._epoch = state, monotonic, state.epoch
        self._deadline = self._now() + max(0, (state.deadline_at - state.server_now).total_seconds())
        self._spans = []
        self._attempt = None

    @property
    def write_binding(self):
        return RunWriteBinding(run_id=self._state.run_id, epoch=self._epoch)

    def _accept(self, state, elapsed=0):
        if (
            state.owner != self._owner
            or state.run_id != self._state.run_id
            or state.epoch != self._epoch
            or state.worker_ticket != self._state.worker_ticket
            or state.worker_nonce != self._state.worker_nonce
        ):
            raise StaleVersionError("Run worker identity or epoch changed")
        self._state = state
        remaining = max(0, (state.deadline_at - state.server_now).total_seconds() - elapsed)
        self._deadline = min(self._deadline, self._now() + remaining)
        return state

    def check(self):
        start = self._now()
        state = self._accept(self._control.read(self._owner, self._state.run_id), self._now() - start)
        if state.status in {"cancelling", "cancelled"}:
            raise TaskCancelled()
        if state.status != "running":
            raise StaleVersionError("Assistant run is already finished")
        if self._now() >= self._deadline:
            raise DeadlineExceeded()

    def remaining(self, native_timeout):
        self.check()
        return min(native_timeout, max(0, self._deadline - self._now()))

    def guarded(self, write):
        # A preflight read and callback do not make a remote write atomic.
        raise ProviderUnavailableError("This write requires an explicit transaction with its run binding")

    def _command(self, cls, **values):
        return cls(
            ticket_id=self._state.worker_ticket,
            nonce=self._state.worker_nonce,
            epoch=self._epoch,
            event_id=uuid4(),
            **values,
        )

    def _send(self, command, *, settling=False):
        timeout = 3 if settling else min(3, self._deadline - self._now())
        if timeout < 2:
            raise DeadlineExceeded()
        start = self._now()
        result = self._verifier.record_run(command, timeout_seconds=timeout)
        return self._accept(result, self._now() - start)

    @contextmanager
    def step(self, kind):
        self.check()
        if any(active == kind for active, _ in self._spans):
            yield
            self.check()
            return
        span, started = uuid4(), self._now()
        self._send(self._command(StartRunStep, span_id=span, step_kind=kind))
        self._spans.append((kind, span))
        if kind == "model":
            self._attempt = None
        try:
            yield
            self.check()
        except BaseException:
            self._send(
                self._command(
                    FinishRunStep, span_id=span, succeeded=False, duration_ms=max(0, (self._now() - started) * 1000)
                ),
                settling=True,
            )
            self.check()
            raise
        else:
            self._send(
                self._command(
                    FinishRunStep, span_id=span, succeeded=True, duration_ms=max(0, (self._now() - started) * 1000)
                ),
                settling=True,
            )
        finally:
            self._spans.pop()

    def model_started(self, model, instruction, tools):
        self.check()
        self._send(
            self._command(
                RecordRunProvider,
                observation={
                    "phase": "metadata",
                    "configured_model": model_name(model),
                    "instruction_hash": content_hash(instruction),
                    "schema_hash": content_hash(tools),
                },
            )
        )

    def sdk_attempt(self):
        self.check()
        span = next((span for kind, span in reversed(self._spans) if kind == "model"), None)
        if span is None:
            raise ProviderUnavailableError("An active model step is required for SDK observation")
        attempt = uuid4()
        self._send(
            self._command(RecordRunProvider, observation={"phase": "attempt", "span_id": span, "attempt_id": attempt})
        )
        self._attempt = attempt

    def model_returned(self, returned_model, usage):
        if self._attempt is None:
            raise ProviderUnavailableError("An observed SDK attempt is required for returned usage")
        self._send(
            self._command(
                RecordRunProvider,
                observation={
                    "phase": "response",
                    "attempt_id": self._attempt,
                    "returned_model": model_name(returned_model),
                    "usage": usage,
                },
            ),
            settling=True,
        )

    def finish(self, status, reason, duration):
        return self._send(self._command(FinishRun, status=status, reason=reason, duration_ms=duration), settling=True)


class DurableAgentExecutionService:
    def __init__(self, *, control, verifier, monotonic, revision, runtime_hash):
        self._control, self._verifier, self._now = control, verifier, monotonic
        self._revision, self._runtime_hash = revision, runtime_hash

    def start(self, owner, run_id):
        self._control.start(owner, run_id, None)

    def read(self, owner, run_id):
        state = self._control.read(owner, run_id)
        if state.status in {"running", "cancelling"} and state.server_now >= state.deadline_at:
            try:
                state = self._verifier.record_run(
                    RecoverInterruptedRun(
                        ticket_id=state.worker_ticket, nonce=state.worker_nonce, epoch=state.epoch, event_id=uuid4()
                    ),
                    timeout_seconds=3,
                )
            except StaleVersionError:
                state = self._control.read(owner, run_id)
        return state.snapshot

    def cancel(self, owner, run_id):
        return self._control.request_cancel(owner, run_id).snapshot

    def execute(self, owner, run_id, work):
        initial = self._control.read(owner, run_id)
        claimed = self._verifier.record_run(
            ClaimRun(
                ticket_id=initial.worker_ticket,
                nonce=initial.worker_nonce,
                epoch=initial.epoch,
                event_id=uuid4(),
                revision=self._revision,
                runtime_hash=self._runtime_hash,
            ),
            timeout_seconds=3,
        )
        if not claimed.claim_acquired:
            raise DuplicateEventError("Run claim was not newly acquired; work must not be replayed")
        control = DurableExecutionControl(
            control=self._control, verifier=self._verifier, owner=owner, state=claimed, monotonic=self._now
        )
        token, started = current_execution.set(control), self._now()
        try:
            with execution_step("application"):
                result = work()
            control.finish("completed", None, max(0, (self._now() - started) * 1000))
            return result
        except BaseException as error:
            state = self._control.read(owner, run_id)
            if state.status in {"running", "cancelling"}:
                cancelled = isinstance(error, TaskCancelled) or state.status == "cancelling"
                reason = (
                    "cancelled"
                    if cancelled
                    else error.reason
                    if isinstance(error, ExecutionStopped)
                    else "execution_failed"
                )
                control.finish("cancelled" if cancelled else "failed", reason, max(0, (self._now() - started) * 1000))
            raise
        finally:
            current_execution.reset(token)
