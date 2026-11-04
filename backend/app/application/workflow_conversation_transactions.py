"""Fixed native transitions replace remote Python write callbacks."""

from uuid import uuid5

from ..contracts.assistant_workflows import validate_workflow_values
from ..contracts.conversation_threads import ConversationResume
from ..contracts.workflow_conversation_transactions import ConversationTransition, ConversationTransitionPort
from ..domain.errors import ProviderUnavailableError, StaleVersionError, ValidationError


class ConversationWorkflowTransactions:
    def __init__(self, *, port: ConversationTransitionPort, tasks, clock, conversations):
        self.port, self.tasks, self.clock, self.conversations = port, tasks, clock, conversations

    def run(self, owner, task_id, revision, capability, target, confirmed, restore):
        if confirmed is not True:
            raise ValidationError("Confirm this conversation action independently")
        task = self.tasks.get(owner, task_id)
        values = validate_workflow_values(capability, task.fields)
        # Clearing detaches conversation-linked tasks and can advance/suspend
        # this very task. Only the fixed transaction may recover its old receipt.
        if (
            task.owner != owner
            or task.capability_id != capability
            or (capability != "conversation.clear" and (task.revision != revision or task.state == "suspended"))
            or task.save_mode != "allowed"
            or task.state == "cancelled"
            or getattr(values, "conversation_id", None) != target
        ):
            raise StaleVersionError("Reopen the current saved conversation action")
        command = ConversationTransition(
            task_id=task_id,
            revision=revision,
            capability_id=capability,
            target=target,
            action_key=uuid5(task_id, f"native-conversation-transition:{revision}"),
            session_id=uuid5(task_id, f"native-conversation-session:{revision}"),
            confirmed=True,
        )
        actual = self.port.execute(owner, command)
        if capability == "conversation.clear":
            if actual.session is not None:
                raise ProviderUnavailableError("Conversation clearing result is unavailable")
            return {"cleared": True}
        session = actual.session
        if session is None or session.patient_id != owner or session.id != command.session_id:
            raise ProviderUnavailableError("Owned native conversation result is unavailable")
        if capability == "conversation.resume":
            if session.conversation_id != target:
                raise ProviderUnavailableError("Actual conversation binding is unavailable")
            return ConversationResume(conversation=self.conversations.require(owner, target), session_id=session.id)
        if restore is None:
            raise ValidationError("Native session response interface is unavailable")
        return restore(session)
