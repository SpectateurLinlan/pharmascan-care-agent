"""One explicit retention policy for tasks, chat/context and fallbacks."""

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from ..contracts.agent_execution import current_execution
from ..contracts.dto import AgentSessionDTO, ToolTraceDTO
from ..contracts.ports import AgentSessionRepository
from ..contracts.workflow_messages import (
    HISTORY_WRITES,
    AppendSafeTrace,
    ConversationPersistencePort,
    ConversationWriteCommand,
    ConversationWriteScope,
    CreateSession,
    UpdateSessionContext,
)
from ..contracts.workflow_record_writes import RecordPreparationCommand, RecordWorkflowWritePort
from ..domain.errors import ProviderUnavailableError


@dataclass(frozen=True)
class MessagePersistencePolicy:
    save_history: bool = True
    save_context: bool = True
    save_task: bool = True
    # Request-local transaction guard supplied by the composition's control port.
    # The callback never enters a model prompt, transport payload or saved context.
    guard: Callable[[Callable[[], None]], bool] | None = field(default=None, repr=False, compare=False)
    messages: ConversationPersistencePort | None = field(default=None, repr=False, compare=False)
    scope: ConversationWriteScope = field(default_factory=ConversationWriteScope)

    def _write(self, allowed: bool, write: Callable[[], None]) -> bool:
        if not allowed:
            return False
        if self.messages is not None:
            raise ProviderUnavailableError("This persistence path requires an explicit conversation command")

        def apply():
            if self.guard is not None:
                return self.guard(write)
            write()
            return True

        control = current_execution.get()
        return control.guarded(apply) if control else apply()

    def write_context(self, write: Callable[[], None]) -> bool:
        return self._write(self.save_context, write)

    def write_history(self, write: Callable[[], None]) -> bool:
        return self._write(self.save_history, write)

    def execute(self, owner, command: ConversationWriteCommand):
        allowed = self.save_history if command.kind in HISTORY_WRITES else self.save_context
        if not allowed:
            return None
        if self.messages is None:
            raise ProviderUnavailableError("Typed conversation persistence unavailable")
        scope = self.scope
        control = current_execution.get()
        if control is not None:
            control.check()
            binding = getattr(control, "write_binding", None)
            if binding is None:
                raise ProviderUnavailableError("This run requires an explicit transactional write binding")
            scope = scope.model_copy(update={"run_binding": binding})
        result = self.messages.execute(owner, command.model_copy(update={"scope": scope}))
        if control is not None:
            control.check()
        return result

    def persist_session(self, repository: AgentSessionRepository, session: AgentSessionDTO, *, create=False) -> bool:
        if self.messages is not None:
            command = CreateSession(session=session) if create else UpdateSessionContext(session=session)
            return self.execute(session.patient_id, command) is not None
        return self._write(self.save_context, lambda: repository.add(session) if create else repository.update(session))

    def prepare_record(self, owner, command: RecordPreparationCommand, records: RecordWorkflowWritePort):
        if not self.save_context or not self.save_task:
            return None
        if (self.messages is None or self.scope.task_id is None
            or command.binding.task_id!=self.scope.task_id or command.binding.task_revision!=self.scope.revision):
            raise ProviderUnavailableError("Open the current patient report workflow before preparing confirmation")
        control=current_execution.get()
        if control is not None:
            control.check()
            binding=getattr(control,"write_binding",None)
            if binding is None:
                raise ProviderUnavailableError("Native preparation requires a transactional run binding")
            command=command.model_copy(update={"binding":command.binding.model_copy(update={"run_binding":binding})})
        result=records.prepare(owner,command)
        if control is not None:
            control.check()
        return result

    @property
    def trace_writer(self) -> Callable[[ToolTraceDTO], bool] | None:
        if self.messages is None:
            return None
        # This is a typed DTO sink, not an arbitrary write callback. Tool schema
        # serialization excludes it; only the verified request graph supplies it.
        return lambda trace: self.execute(trace.patient_id, AppendSafeTrace(trace=trace)) is not None

    @property
    def can_save_task(self) -> bool:
        if self.messages is not None:
            # The actual task transaction rechecks permission; this is only a UI
            # routing hint and can never authorize a write by itself.
            return self.save_task
        return self._write(self.save_task, lambda: None)


DEFAULT_PERSISTENCE = MessagePersistencePolicy()


def retention_command(text: str) -> Literal["cancel_save", "allow_save"] | None:
    value = unicodedata.normalize("NFKC", text).strip().casefold().rstrip(".!。！")
    if value in {
        "不保存",
        "不要保存",
        "取消保存",
        "禁止保存",
        "不保存本次办理",
        "取消本次保存",
        "don't save",
        "do not save",
        "cancel saving",
        "don't save this workflow",
    }:
        return "cancel_save"
    if value in {"现在保存药物并继续核对", "save this medication and continue review"}:
        return "allow_save"
    return None
