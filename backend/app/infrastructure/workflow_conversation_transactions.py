"""One fixed same-JWT RPC, returning actual native rows instead of cached bodies."""

from ..contracts.workflow_conversation_transactions import ConversationTransition, ConversationTransitionResult
from ..domain.errors import ProviderUnavailableError


class SupabaseConversationTransitions:
    def __init__(self, data):
        self.data = data

    def execute(self, owner, command):
        self.data.check_patient(owner)
        command = ConversationTransition.model_validate(command.model_dump())
        raw = self.data.request(
            "POST",
            "/rest/v1/rpc/assistant_conversation_transition",
            body={"p_command": command.model_dump(mode="json")},
        )
        try:
            result = ConversationTransitionResult.model_validate(raw)
            if result.session is not None and (
                result.session.patient_id != owner
                or result.session.id != command.session_id
                or result.session.conversation_id != command.target
            ):
                raise ValueError
            if (command.capability_id == "conversation.clear") != (result.session is None):
                raise ValueError
            return result
        except (ValueError, TypeError):
            raise ProviderUnavailableError("Native conversation result binding unavailable") from None
