"""Fixed conversation transactions; recording tests do not prove real SQL."""

from contextlib import nullcontext

from ..contracts.workflow_messages import (
    HISTORY_WRITES,
    MESSAGE_COMMAND,
    MESSAGE_RESULT,
    ConversationClaimResult,
    MessageWriteAck,
    SavedConversationMessage,
)
from ..domain.errors import NotFoundError, ProviderUnavailableError, StaleVersionError, ValidationError


def _owned_body(owner, command):
    for name in ("session", "turn", "trace"):
        row = getattr(command, name, None)
        if row is not None and row.patient_id != owner:
            raise ValidationError("Conversation transaction belongs to another patient")


class SupabaseConversationPersistence:
    def __init__(self, data):
        self._data = data

    def execute(self, owner, command):
        self._data.check_patient(owner)
        command = MESSAGE_COMMAND.validate_python(command)
        _owned_body(owner, command)
        payload = command.model_dump(
            mode="json", exclude={name: {"patient_id"} for name in ("session", "turn", "trace")}
        )
        raw = self._data.request("POST", "/rest/v1/rpc/assistant_message_command", body={"p_command": payload})
        if not isinstance(raw, dict) or set(raw) not in ({"result"}, {"error"}):
            raise ProviderUnavailableError("Conversation transaction response unavailable")
        if "error" in raw:
            kinds = {"stale": StaleVersionError, "not_found": NotFoundError, "invalid": ValidationError}
            code = raw["error"]
            cls = kinds.get(code, ProviderUnavailableError) if isinstance(code, str) else ProviderUnavailableError
            raise cls("Conversation saving changed; inspect its current state")
        try:
            result = MESSAGE_RESULT.validate_python(raw["result"])
            wanted = "claim" if command.kind == "claim_turn" else "message" if command.kind == "append_turn" else "ack"
            if result.kind != wanted:
                raise ValueError
            if result.kind == "message" and (
                result.message.id != command.message.id
                or result.message.conversation_id != command.message.conversation_id
            ):
                raise ValueError
            return result
        except (ValueError, TypeError):
            raise ProviderUnavailableError("Conversation transaction result binding unavailable") from None


class MemoryConversationPersistence:
    def __init__(self, *, state, sessions, threads, history, preferences, traces=None, clock=None):
        self._state, self._sessions, self._threads, self._history = state, sessions, threads, history
        self._preferences, self._traces = preferences, traces
        self._clock = clock

    def execute(self, owner, command):
        command = MESSAGE_COMMAND.validate_python(command)
        _owned_body(owner, command)
        with self._state.lock, self._preferences.history_fence() if command.kind in HISTORY_WRITES else nullcontext():
            scope = command.scope
            if scope.task_id is not None:
                control = self._state.controls.get((owner, scope.task_id))
                if (
                    control is None
                    or control.revision != scope.revision
                    or control.mode != "allowed"
                    or control.revoked
                ):
                    raise StaleVersionError("Conversation task saving permission changed")
            if scope.run_binding is not None:
                self._state.require_durable_run(
                    owner, scope.run_binding, self._clock.now() if self._clock is not None else None
                )
            if command.kind in HISTORY_WRITES and not self._preferences.get(owner).conversation_history_enabled:
                raise StaleVersionError("Conversation history saving is disabled")
            return self._execute(owner, command)

    def _execute(self, owner, command):
        kind = command.kind
        if kind == "create_conversation":
            if self._threads.get(owner, command.conversation.id) is None:
                self._threads.create(owner, command.conversation)
        elif kind == "create_session":
            old = self._sessions.get(owner, command.session.id)
            if old is not None and old != command.session:
                raise StaleVersionError("An existing session cannot be replaced")
            if old is None:
                self._sessions.add(command.session)
        elif kind in {"update_context", "bind_session"}:
            old = self._sessions.get(owner, command.session.id)
            if old is None:
                raise NotFoundError("Assistant session unavailable")
            if old.conversation_id not in {None, command.session.conversation_id}:
                raise StaleVersionError("Session conversation changed")
            self._sessions.update(command.session)
        elif kind == "claim_turn":
            status = self._threads.claim(owner, command.conversation_id, command.turn_id, command.digest)
            return ConversationClaimResult(status=status)
        elif kind == "append_turn":
            session = self._sessions.get(owner, command.session_id)
            if session is None or session.conversation_id != command.message.conversation_id:
                raise NotFoundError("Owned conversation session required")
            return SavedConversationMessage(message=self._threads.append(owner, command.session_id, command.message))
        elif kind == "fail_turn":
            self._threads.fail(owner, command.turn_id)
        elif kind == "append_legacy_history":
            if self._sessions.get(owner, command.turn.session_id) is None:
                raise NotFoundError("Owned history session required")
            self._history.append(command.turn)
        elif kind == "clear_history":
            for key, task in tuple(self._state.tasks.items()):
                if key[0] == owner and task.conversation_id is not None:
                    self._state.tasks[key] = task.model_copy(
                        update={
                            "conversation_id": None,
                            "revision": task.revision + 1,
                            "state": task.state if task.state in {"completed", "cancelled"} else "suspended",
                        }
                    )
            for key, control in tuple(self._state.controls.items()):
                if key[0] == owner and control.conversation_id is not None:
                    self._state.controls[key] = control.model_copy(
                        update={
                            "conversation_id": None,
                            "revision": control.revision + 1,
                            "processing_event_id": None,
                            "lease_until": None,
                            "status": control.status if control.status in {"completed", "cancelled"} else "suspended",
                        }
                    )
            self._history.clear(owner)
            self._threads.clear(owner)
            self._sessions.clear_conversation_text(owner)
            self._sessions.detach_conversations(owner)
        elif kind == "append_safe_trace":
            if self._traces is None:
                raise ProviderUnavailableError("Typed trace persistence unavailable")
            if self._sessions.get(owner, command.trace.session_id) is None:
                raise NotFoundError("Owned trace session required")
            self._traces.add(command.trace)
        return MessageWriteAck()
