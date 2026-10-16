"""Reserve before model calls; count successful user turns only, not rounds."""

import hashlib
import logging
from dataclasses import replace
from uuid import UUID

from ..agent.conversation import ConversationService
from ..agent.knowledge_intent import medication_question
from ..agent.orchestrator import AgentOrchestrator, AgentReply, AgentTurn
from ..contracts.enums import AgentIntent
from ..contracts.model import ModelProviderError
from ..contracts.quota import QuotaRepository, Usage
from ..domain.errors import DomainError, ProviderUnavailableError
from ..domain.health_safety import needs_urgent_help_notice

USER_LIMIT = {
    "en": (
        "You've reached today's AI demo limit. This demo uses a limited free AI allowance. "
        "You can continue using your medication records and other non-AI features, "
        "and AI assistance will be available again after 12:00 AM Singapore time. "
        "Higher usage options may be offered in a future version."
    ),
    "zh": (
        "您今天的 AI 演示额度已用完。当前演示版使用有限的免费 AI 额度。"
        "您仍可以查看用药记录和使用其他非 AI 功能，AI 助手将在新加坡时间凌晨 12 点后恢复使用。"
        "未来版本可能会根据实际需求提供更高用量的方案。"
    ),
}
PROVIDER_LIMIT = {
    "en": (
        "AI assistance is temporarily unavailable because the demo service has reached "
        "its current free usage capacity. "
        "Your medication records and non-AI features are still available. Please try again later."
    ),
    "zh": (
        "AI 助手暂时不可用，因为演示服务已达到当前免费使用额度。您的用药记录及其他非 AI 功能仍可正常使用，请稍后再试。"
    ),
}
LOGGER = logging.getLogger("pharmascan.agent.quota")


class QuotaAgent:
    def __init__(
        self,
        *,
        repository: QuotaRepository,
        conversation: ConversationService,
        fallback: AgentOrchestrator,
        daily_limit: int = 20,
    ):
        self._repository, self._conversation, self._fallback, self._limit = (
            repository,
            conversation,
            fallback,
            daily_limit,
        )

    def usage(self, patient_id: UUID) -> Usage:
        return self._repository.usage(patient_id)

    def handle_turn(self, *, patient_id: UUID, session_id: UUID, turn: AgentTurn) -> AgentReply:
        if needs_urgent_help_notice(turn.text):
            return replace(
                self._fallback.handle_turn(patient_id=patient_id, session_id=session_id, turn=turn),
                usage=self.usage(patient_id),
            )
        usage = self.usage(patient_id)
        if usage.limit != self._limit:
            raise ProviderUnavailableError("Demo quota configuration needs administrative review")
        turn_key = (
            "agent-" + hashlib.sha256(f"{session_id}:{turn.slots.get('client_turn_id', 'turn-1')}".encode()).hexdigest()
        )
        reservation = self._repository.reserve(patient_id, turn_key)
        session = self._fallback.get_session(patient_id=patient_id, session_id=session_id)
        if reservation.state != "reserved":
            message = (
                USER_LIMIT[turn.language]
                if reservation.state == "exhausted"
                else "This request is already processed or another turn is in progress. Your records remain available."
            )
            return AgentReply(
                message=message,
                intent=AgentIntent.CLARIFICATION,
                session_id=session_id,
                session_state=session.state,
                mode="quota_limited",
                usage=reservation.usage,
            )
        try:
            reply = self._conversation.handle_turn(
                patient_id=patient_id,
                session_id=session_id,
                turn=turn,
                on_model_request=lambda: self._repository.model_request(patient_id, reservation),
            )
        except ModelProviderError as exc:
            LOGGER.warning("Model provider fallback category=%s", exc.category)
            snapshot = self._repository.finish(patient_id, reservation, False)
            if medication_question(turn.text):
                knowledge = self._conversation.medication_fallback(
                    patient_id=patient_id, session_id=session_id, turn=turn
                )
                if knowledge:
                    return replace(knowledge, usage=snapshot)
            fallback = self._fallback.handle_turn(patient_id=patient_id, session_id=session_id, turn=turn)
            message = (
                PROVIDER_LIMIT[turn.language]
                if exc.category == "quota"
                else (
                    "AI assistance is temporarily unavailable. "
                    "Your medication records and text actions remain available."
                )
            )
            return replace(
                fallback, message=message + " " + fallback.message, mode="deterministic_degraded", usage=snapshot
            )
        except DomainError:
            self._repository.finish(patient_id, reservation, False)
            raise
        snapshot = self._repository.finish(patient_id, reservation, reply.mode == "gemini")
        return replace(reply, usage=snapshot)
