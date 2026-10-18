"""Opt-in durable conversations; never replay historical tool/confirmation state."""

from __future__ import annotations

from uuid import UUID

from ..contracts.agent_context import AgentContext, RecentTurn
from ..contracts.context_bounds import bounded_context
from ..contracts.conversation_threads import (
    ConversationList,
    ConversationPage,
    ConversationResume,
    ConversationSummary,
    ConversationThreads,
)
from ..contracts.ports import AgentSessionRepository, Clock
from ..contracts.privacy import bounded_text
from ..domain.errors import NotFoundError, ValidationError
from .preferences import PreferenceService


class ConversationThreadService:
    def __init__(
        self,
        repository: ConversationThreads,
        sessions: AgentSessionRepository,
        clock: Clock,
        preferences: PreferenceService,
    ):
        self._repository, self._sessions, self._clock = repository, sessions, clock
        self._preferences = preferences

    def _consented(self, owner):
        if not self._preferences.get(owner).conversation_history_enabled:
            raise ValidationError("Conversation saving is disabled")

    def require(self, owner: UUID, conversation_id: UUID) -> ConversationSummary:
        row = self._repository.get(owner, conversation_id)
        if row is None:
            raise NotFoundError("Conversation not found for this patient")
        return row

    def create(self, owner: UUID, conversation_id: UUID, text: str, photo: bool) -> ConversationSummary:
        self._consented(owner)
        existing = self._repository.get(owner, conversation_id)
        if existing is not None:
            return existing
        now = self._clock.now()
        title = " ".join(bounded_text(text, 120).split())
        if title.startswith(("{", "[")):
            title = ""
        title = title or ("Photo attachment" if photo else "Conversation")
        row = ConversationSummary(id=conversation_id, title=title, created_at=now, updated_at=now)
        self._repository.create(owner, row)
        return row

    def list(self, owner: UUID, before: UUID | None = None, limit: int = 20) -> ConversationList:
        rows = self._repository.list(owner, before, limit + 1)
        return ConversationList(entries=rows[:limit], next_before=rows[limit - 1].id if len(rows) > limit else None)

    def page(self, owner: UUID, conversation_id: UUID, before: UUID | None = None, limit: int = 50) -> ConversationPage:
        row = self.require(owner, conversation_id)
        entries = self._repository.messages(owner, conversation_id, before, limit + 1)
        return ConversationPage(
            conversation=row,
            entries=list(reversed(entries[:limit])),
            next_before=entries[limit - 1].id if len(entries) > limit else None,
        )

    def bind(self, owner: UUID, conversation_id: UUID, session_id: UUID, *, restore: bool):
        self.require(owner, conversation_id)
        session = self._sessions.get(owner, session_id)
        if session is None:
            raise NotFoundError("Assistant session not found for this patient")
        if session.conversation_id not in (None, conversation_id):
            raise ValidationError("Session belongs to another conversation")
        if not restore and session.conversation_id == conversation_id:
            return session
        if session.state != "collecting" or session.context.recent_turns:
            raise ValidationError("Use a fresh assistant session to restore a conversation")
        rows = list(reversed(self._repository.messages(owner, conversation_id, None, 6))) if restore else []
        context = bounded_context(
            AgentContext(
                recent_turns=[
                    RecentTurn(user=bounded_text(row.user_text, 500), assistant=bounded_text(row.assistant_text, 700))
                    for row in rows
                ]
            )
        )
        session = session.model_copy(update={"conversation_id": conversation_id, "context": context})
        self._sessions.update(session)
        return session

    def resume(self, owner: UUID, conversation_id: UUID, fresh_session_id: UUID) -> ConversationResume:
        session = self.bind(owner, conversation_id, fresh_session_id, restore=True)
        return ConversationResume(conversation=self.require(owner, conversation_id), session_id=session.id)

    def claim(self, owner, conversation_id, turn_id, digest):
        self._consented(owner)
        self.require(owner, conversation_id)
        return self._repository.claim(owner, conversation_id, turn_id, digest)

    def message(self, owner, turn_id):
        return self._repository.message(owner, turn_id)

    def append(self, owner, session_id, row):
        self._consented(owner)
        return self._repository.append(owner, session_id, row)

    def fail(self, owner, turn_id):
        self._repository.fail(owner, turn_id)

    def clear(self, owner):
        self._repository.clear(owner)
