"""Opt-in bounded chat retention, no tool execution or patient fact mutation."""

from datetime import timedelta
from uuid import UUID, uuid5

from ..contracts.conversation_history import ConversationHistoryRepository, HistoryEntry, HistoryPage, HistoryTurn
from ..contracts.ports import Clock
from ..contracts.privacy import bounded_text
from ..contracts.workflow_messages import AppendLegacyHistory
from ..domain.errors import ValidationError
from .workflow_message_policy import DEFAULT_PERSISTENCE, MessagePersistencePolicy


class ConversationHistoryService:
    def __init__(self, repository: ConversationHistoryRepository, clock: Clock):
        self._repository, self._clock = repository, clock

    def append(
        self,
        patient_id: UUID,
        session_id: UUID,
        turn_id: str,
        text: str,
        message: str,
        *,
        policy: MessagePersistencePolicy = DEFAULT_PERSISTENCE,
    ) -> bool:
        if policy.messages is not None:
            if not policy.save_history:
                return False
            row = HistoryTurn(id=uuid5(session_id, turn_id), patient_id=patient_id, session_id=session_id,
                              user_text=bounded_text(text, 2000), assistant_text=bounded_text(message, 4000),
                              created_at=self._clock.now())
            return policy.execute(patient_id, AppendLegacyHistory(turn=row)) is not None
        return policy.write_history(
            lambda: self._repository.append(
                HistoryTurn(
                    id=uuid5(session_id, turn_id),
                    patient_id=patient_id,
                    session_id=session_id,
                    user_text=bounded_text(text, 2000),
                    assistant_text=bounded_text(message, 4000),
                    created_at=self._clock.now(),
                )
            )
        )

    def page(self, patient_id: UUID, before: UUID | None = None, limit: int = 20) -> HistoryPage:
        if not 1 <= limit <= 20:
            raise ValidationError("Choose a history page of1..20 messages")
        rows = self._repository.page(patient_id, self._clock.now() - timedelta(days=30), before, limit + 1)
        selected = rows[:limit]
        return HistoryPage(
            entries=[
                HistoryEntry.model_validate(row.model_dump(exclude={"patient_id", "session_id"})) for row in selected
            ],
            next_before=selected[-1].id if len(rows) > limit else None,
        )

    def clear(self, patient_id: UUID, *, confirmed: bool) -> None:
        if not confirmed:
            raise ValidationError("Confirm clearing conversation history")
        self._repository.clear(patient_id)
