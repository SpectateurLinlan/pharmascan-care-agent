"""Same-user JWT history adapter and clearly simulated local adapter."""

from collections.abc import Callable
from datetime import datetime
from threading import RLock
from uuid import UUID

from ..contracts.conversation_history import HistoryTurn
from ..domain.errors import NotFoundError, ValidationError
from .supabase_data import SupabaseDataClient


class MemoryConversationHistory:
    """SIMULATED, owned by one composition root; never a process-global cache."""

    def __init__(self, clear_context: Callable[[UUID], None] | None = None):
        self._rows: dict[tuple[UUID, UUID], HistoryTurn] = {}
        self._lock = RLock()
        self._clear_context = clear_context

    def append(self, row: HistoryTurn) -> None:
        with self._lock:
            key = (row.patient_id, row.id)
            old = self._rows.get(key)
            if old and (old.user_text, old.assistant_text) != (row.user_text, row.assistant_text):
                raise ValidationError("Conversation retry differs from the saved turn")
            self._rows.setdefault(key, row)
            own = sorted(
                (v for v in self._rows.values() if v.patient_id == row.patient_id),
                key=lambda v: (v.created_at, v.id),
                reverse=True,
            )
            for item in own[200:]:
                del self._rows[(item.patient_id, item.id)]

    def page(self, patient_id: UUID, since: datetime, before: UUID | None, limit: int) -> list[HistoryTurn]:
        with self._lock:
            anchor = self._rows.get((patient_id, before)) if before else None
            if before and anchor is None:
                raise NotFoundError("Conversation page unavailable")
            return sorted(
                (
                    row
                    for row in self._rows.values()
                    if row.patient_id == patient_id
                    and row.created_at >= since
                    and (not anchor or (row.created_at, row.id) < (anchor.created_at, anchor.id))
                ),
                key=lambda row: (row.created_at, row.id),
                reverse=True,
            )[:limit]

    def clear(self, patient_id: UUID) -> None:
        with self._lock:
            self._rows = {key: row for key, row in self._rows.items() if key[0] != patient_id}
            if self._clear_context:
                self._clear_context(patient_id)


class SupabaseConversationHistory:
    def __init__(self, client: SupabaseDataClient):
        self._client = client

    def append(self, row: HistoryTurn) -> None:
        self._client.check_patient(row.patient_id)
        self._client.request(
            "POST", "/rest/v1/rpc/append_conversation_turn", body={"p_turn": row.model_dump(mode="json")}
        )

    def page(self, patient_id: UUID, since: datetime, before: UUID | None, limit: int) -> list[HistoryTurn]:
        self._client.check_patient(patient_id)
        filters = {
            "conversation_id": "is.null",
            "patient_id": f"eq.{patient_id}",
            "created_at": f"gte.{since.isoformat()}",
            "order": "created_at.desc,id.desc",
            "limit": str(limit),
        }
        if before:
            rows = self._client.rows("conversation_turns", patient_id=f"eq.{patient_id}", id=f"eq.{before}", limit="1")
            if not rows:
                raise NotFoundError("Conversation page unavailable")
            stamp = HistoryTurn.model_validate(
                {k: v for k, v in rows[0].items() if k in HistoryTurn.model_fields}
            ).created_at.isoformat()
            filters["or"] = f"(created_at.lt.{stamp},and(created_at.eq.{stamp},id.lt.{before}))"
        return [
            HistoryTurn.model_validate({k: v for k, v in row.items() if k in HistoryTurn.model_fields})
            for row in self._client.rows("conversation_turns", **filters)
        ]

    def clear(self, patient_id: UUID) -> None:
        self._client.check_patient(patient_id)
        self._client.request("POST", "/rest/v1/rpc/clear_conversation_history", body={})
