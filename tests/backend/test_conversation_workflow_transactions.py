"""DEMO_ONLY typed conversation transitions do not invoke legacy writers."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4, uuid5

import pytest
from app.application.workflow_conversation_transactions import ConversationWorkflowTransactions
from app.contracts.conversation_threads import ConversationSummary
from app.contracts.dto import AgentSessionDTO
from app.contracts.workflow_conversation_transactions import ConversationTransitionResult
from app.domain.errors import StaleVersionError, ValidationError

from .test_persistent_workflow_composition import persistent_root


@pytest.mark.parametrize("capability", ["conversation.new", "conversation.resume", "conversation.clear"])
def test_typed_transition_uses_owned_task_and_never_calls_legacy_writer(monkeypatch, capability):
    from types import SimpleNamespace

    owner, task_id, target = uuid4(), uuid4(), uuid4() if capability == "conversation.resume" else None
    calls = []
    now = datetime(2026, 10, 30, tzinfo=UTC)
    task = SimpleNamespace(
        id=task_id,
        owner=owner,
        revision=3,
        capability_id=capability,
        fields={"conversation_id": target} if target else {},
        save_mode="allowed",
        state="awaiting_confirmation",
    )

    class Port:
        def execute(self, current_owner, command):
            if command.revision != 3:
                raise StaleVersionError("DEMO SQL current revision check")
            calls.append(command)
            assert current_owner == owner and command.task_id == task_id and command.target == target
            session = (
                None
                if capability == "conversation.clear"
                else AgentSessionDTO(
                    id=uuid5(task_id, "native-conversation-session:3"),
                    patient_id=owner,
                    intent=None,
                    conversation_id=target,
                    state="collecting",
                    state_version=1,
                    pending_field_names=[],
                    updated_at=now,
                    expires_at=now + timedelta(minutes=20),
                )
            )
            return ConversationTransitionResult(session=session)

    coordinator = ConversationWorkflowTransactions(
        port=Port(),
        tasks=SimpleNamespace(get=lambda o, t: task),
        clock=SimpleNamespace(now=lambda: now),
        conversations=SimpleNamespace(
            require=lambda o, t: ConversationSummary(id=target, title="DEMO_ONLY", created_at=now, updated_at=now)
        ),
    )

    def restore(s):
        return s.id

    output = coordinator.run(owner, task_id, 3, capability, target, True, restore)
    assert (
        output == {"cleared": True}
        if capability == "conversation.clear"
        else output.session_id == uuid5(task_id, "native-conversation-session:3")
        if target
        else output == uuid5(task_id, "native-conversation-session:3")
    )
    assert len(calls) == 1
    with pytest.raises(ValidationError):
        coordinator.run(owner, task_id, 3, capability, target, False, restore)
    with pytest.raises(StaleVersionError):
        coordinator.run(owner, task_id, 2, capability, target, True, restore)


def test_candidate_conversation_handler_has_typed_transition_dependency(monkeypatch):
    _, scoped, _, _, _ = persistent_root(monkeypatch)
    service = scoped("DEMO-A").assistant_candidate.container.assistant_conversations
    assert service.transactions is not None


def test_clear_response_recovery_survives_its_own_native_conversation_detachment():
    from types import SimpleNamespace

    owner, task_id = uuid4(), uuid4()
    task = SimpleNamespace(
        id=task_id,
        owner=owner,
        revision=3,
        capability_id="conversation.clear",
        fields={},
        save_mode="allowed",
        state="awaiting_confirmation",
    )
    keys = set()

    class Port:
        def execute(self, o, command):
            keys.add(command.action_key)
            task.revision = 4
            task.state = "suspended"
            return ConversationTransitionResult()

    tx = ConversationWorkflowTransactions(
        port=Port(), tasks=SimpleNamespace(get=lambda *a: task), clock=SimpleNamespace(), conversations=None
    )
    assert tx.run(owner, task_id, 3, "conversation.clear", None, True, None) == {"cleared": True}
    assert tx.run(owner, task_id, 3, "conversation.clear", None, True, None) == {"cleared": True}
    assert len(keys) == 1
