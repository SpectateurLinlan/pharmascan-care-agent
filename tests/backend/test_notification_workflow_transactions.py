"""DEMO_ONLY task-bound subscriptions never use an arbitrary callback."""

from uuid import uuid4

import pytest
from app.application.workflow_notification_transactions import NotificationWorkflowTransactions
from app.domain.errors import ValidationError

from .test_persistent_workflow_composition import persistent_root


def test_patient_subscription_uses_closed_port_and_requires_explicit_confirmation():
    owner, task_id, target = uuid4(), uuid4(), uuid4()
    commands = []

    class Port:
        def execute(self, o, cmd):
            assert o == owner
            commands.append(cmd)
            return None

    tx = NotificationWorkflowTransactions(port=Port())
    assert tx.run(owner, task_id, 2, "notification.unsubscribe", True, subscription_id=target) is None
    assert commands[0].subscription_id == target
    with pytest.raises(ValidationError):
        tx.run(owner, task_id, 2, "notification.unsubscribe", False, subscription_id=target)
    with pytest.raises(ValidationError):
        tx.run(owner, task_id, 2, "notification.test", True)
    with pytest.raises(ValueError):
        tx.run(owner, task_id, 2, "notification.unsubscribe", True)
    assert len(commands) == 1


def test_candidate_notification_handler_has_typed_dependency(monkeypatch):
    _, scoped, _, _, _ = persistent_root(monkeypatch)
    assert scoped("DEMO-A").assistant_candidate.container.assistant_notifications.transactions is not None
