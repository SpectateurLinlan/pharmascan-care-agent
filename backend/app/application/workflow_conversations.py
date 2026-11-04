"""Native conversation receipts prevent duplicate session creation or destructive retries."""

from collections.abc import Callable
from uuid import UUID, uuid5

from ..agent.orchestrator import AgentOrchestrator
from ..contracts.assistant_workflows import ActionRepository, BusinessRef
from ..contracts.conversation_threads import ConversationResume
from ..contracts.dto import AgentSessionDTO
from ..domain.errors import NotFoundError, StaleVersionError, ValidationError
from .assistant_workflows import WorkflowService
from .conversation_history import ConversationHistoryService
from .conversation_threads import ConversationThreadService


class WorkflowConversationService:
    def __init__(
        self,
        *,
        workflows: WorkflowService,
        actions: ActionRepository,
        orchestrator: AgentOrchestrator,
        conversations: ConversationThreadService,
        history: ConversationHistoryService,
        transactions=None,
    ):
        self.workflows, self.actions, self.orchestrator = workflows, actions, orchestrator
        self.conversations, self.history = conversations, history
        self.transactions = transactions

    def run(
        self,
        owner: UUID,
        task_id: UUID,
        revision: int,
        capability: str,
        target: UUID | None,
        confirmed: bool,
        write: Callable[[], object],
        restore: Callable[[AgentSessionDTO], object] | None,
    ):
        if self.transactions is not None:
            return self.transactions.run(owner, task_id, revision, capability, target, confirmed, restore)
        if not confirmed:
            raise ValidationError("Confirm this conversation action independently")

        def checked(context, values):
            if getattr(values, "conversation_id", None) != target:
                raise ValidationError("The selected conversation does not match this task")
            if target:
                self.conversations.require(owner, target)
            key = uuid5(task_id, "native-conversation-transition")
            try:
                receipt = self.actions.read(owner, key)
            except NotFoundError:
                receipt = self.actions.reserve(context, key)
            else:
                if receipt.binding_revision != revision:
                    raise StaleVersionError("Start a new task after changing an attempted conversation action")
                if receipt.state != "succeeded" or receipt.business_ref is None:
                    raise StaleVersionError("The earlier conversation result is uncertain; do not repeat it")
                ref = receipt.business_ref
                if capability == "conversation.clear":
                    return {"cleared": True}
                session = self.orchestrator.get_session(patient_id=owner, session_id=ref.id)
                if session is None:
                    raise StaleVersionError("The earlier native session is unavailable")
                if capability == "conversation.resume":
                    return ConversationResume(conversation=self.conversations.require(owner, target), session_id=ref.id)
                if restore is None:
                    raise ValidationError("The native session restoration interface is unavailable")
                return restore(session)
            self.actions.complete(context, receipt.model_copy(update={"state": "outcome_unknown"}))
            result = write()
            if capability == "conversation.clear":
                if self.conversations.list(owner).entries or self.history.page(owner).entries:
                    raise StaleVersionError("Conversation clearing could not be verified")
                ref = BusinessRef(kind="conversation_cleanup", id=key)
            else:
                session_id = result.session_id
                if self.orchestrator.get_session(patient_id=owner, session_id=session_id) is None:
                    raise StaleVersionError("The native session could not be verified")
                ref = BusinessRef(kind="agent_session", id=session_id)
            self.actions.complete(context, receipt.model_copy(update={"state": "succeeded", "business_ref": ref}))
            return result

        return self.workflows.guarded_conversation_action(owner, task_id, revision, capability, checked)
