"""Injected memory and same-user JWT persistence; no privileged patient path."""

from threading import RLock
from uuid import UUID

from ..contracts.conversation_threads import ConversationMessage, ConversationSummary
from ..domain.errors import NotFoundError, ValidationError
from .supabase_data import SupabaseDataClient


class MemoryConversationThreads:
    def __init__(self):
        self._threads: dict[tuple[UUID, UUID], ConversationSummary] = {}
        self._messages: dict[tuple[UUID, UUID], ConversationMessage] = {}
        self._claims: dict[tuple[UUID, UUID], tuple[UUID, str, str]] = {}
        self._lock = RLock()

    def create(self, owner, row):
        with self._lock:
            if any(key[1] == row.id for key in self._threads):
                raise ValidationError("Conversation already exists")
            self._threads[(owner, row.id)] = row

    def get(self, owner, conversation_id):
        with self._lock:
            return self._threads.get((owner, conversation_id))

    def list(self, owner, before, limit):
        with self._lock:
            threads = tuple(self._threads.items())
            messages = tuple(self._messages.items())
        anchor = self.get(owner, before) if before else None
        if before and anchor is None:
            raise NotFoundError("Conversation page unavailable")
        return sorted(
            (
                row
                for (patient, _), row in threads
                if patient == owner
                and any(p == owner and msg.conversation_id == row.id for (p, _), msg in messages)
                and (anchor is None or (row.updated_at, row.id) < (anchor.updated_at, anchor.id))
            ),
            key=lambda row: (row.updated_at, row.id),
            reverse=True,
        )[:limit]

    def messages(self, owner, conversation_id, before, limit):
        with self._lock:
            messages = tuple(self._messages.items())
        anchor = self.message(owner, before) if before else None
        if before and (anchor is None or anchor.conversation_id != conversation_id):
            raise NotFoundError("Conversation page unavailable")
        return sorted(
            (
                row
                for (p, _), row in messages
                if p == owner
                and row.conversation_id == conversation_id
                and (anchor is None or (row.created_at, row.id) < (anchor.created_at, anchor.id))
            ),
            key=lambda row: (row.created_at, row.id),
            reverse=True,
        )[:limit]

    def claim(self, owner, conversation_id, turn_id, digest):
        with self._lock:
            if self.get(owner, conversation_id) is None:
                raise NotFoundError("Conversation unavailable")
            prior = self._claims.get((owner, turn_id))
            if prior:
                if prior[:2] != (conversation_id, digest):
                    raise ValidationError("Message retry differs from original")
                return "completed" if prior[2] == "completed" else "busy"
            self._claims[(owner, turn_id)] = (conversation_id, digest, "processing")
            return "new"

    def message(self, owner, turn_id):
        with self._lock:
            return self._messages.get((owner, turn_id))

    def append(self, owner, session_id, row):
        with self._lock:
            key = (owner, row.id)
            if key in self._messages:
                return self._messages[key]
            thread = self.get(owner, row.conversation_id)
            if thread is None or key not in self._claims:
                raise ValidationError("Claim required")
            if self._claims[key][0] != row.conversation_id or self._claims[key][2] != "processing":
                raise ValidationError("Owned processing claim required")
            self._messages[key] = row
            self._threads[(owner, thread.id)] = thread.model_copy(update={"updated_at": row.created_at})
            claim = self._claims[key]
            self._claims[key] = (*claim[:2], "completed")
            return row

    def fail(self, owner, turn_id):
        with self._lock:
            key = (owner, turn_id)
            if key in self._claims and self._claims[key][2] == "processing":
                old = self._claims[key]
                self._claims[key] = (*old[:2], "failed")

    def clear(self, owner):
        with self._lock:
            self._messages = {key: row for key, row in self._messages.items() if key[0] != owner}
            self._threads = {key: row for key, row in self._threads.items() if key[0] != owner}
            self._claims = {key: row for key, row in self._claims.items() if key[0] != owner}


class SupabaseConversationThreads:
    def __init__(self, client: SupabaseDataClient):
        self._client = client

    def create(self, owner, row):
        self._client.check_patient(owner)
        self._client.request(
            "POST", "/rest/v1/rpc/create_conversation", body={"p_id": str(row.id), "p_title": row.title}
        )

    def get(self, owner, conversation_id):
        self._client.check_patient(owner)
        rows = self._client.rows(
            "conversations",
            patient_id=f"eq.{owner}",
            id=f"eq.{conversation_id}",
            select="id,title,created_at,updated_at",
            limit="1",
        )
        return ConversationSummary.model_validate(rows[0]) if rows else None

    def list(self, owner, before, limit):
        self._client.check_patient(owner)
        filters = {
            "patient_id": f"eq.{owner}",
            "has_messages": "eq.true",
            "select": "id,title,created_at,updated_at",
            "order": "updated_at.desc,id.desc",
            "limit": str(limit),
        }
        if before:
            anchor = self.get(owner, before)
            if anchor is None:
                raise NotFoundError("Conversation page unavailable")
            stamp = anchor.updated_at.isoformat()
            filters["or"] = f"(updated_at.lt.{stamp},and(updated_at.eq.{stamp},id.lt.{before}))"
        return [ConversationSummary.model_validate(row) for row in self._client.rows("conversations", **filters)]

    def messages(self, owner, conversation_id, before, limit):
        self._client.check_patient(owner)
        filters = {
            "patient_id": f"eq.{owner}",
            "conversation_id": f"eq.{conversation_id}",
            "select": "id,conversation_id,user_text,assistant_text:full_assistant_text,photo_attached,created_at",
            "order": "created_at.desc,id.desc",
            "limit": str(limit),
        }
        if before:
            anchor = self.message(owner, before)
            if anchor is None or anchor.conversation_id != conversation_id:
                raise NotFoundError("Conversation page unavailable")
            stamp = anchor.created_at.isoformat()
            filters["or"] = f"(created_at.lt.{stamp},and(created_at.eq.{stamp},id.lt.{before}))"
        return [ConversationMessage.model_validate(row) for row in self._client.rows("conversation_turns", **filters)]

    def claim(self, owner, conversation_id, turn_id, digest):
        self._client.check_patient(owner)
        return self._client.request(
            "POST",
            "/rest/v1/rpc/claim_conversation_turn",
            body={"p_conversation": str(conversation_id), "p_id": str(turn_id), "p_digest": digest},
        )

    def message(self, owner, turn_id):
        self._client.check_patient(owner)
        rows = self._client.rows(
            "conversation_turns",
            patient_id=f"eq.{owner}",
            id=f"eq.{turn_id}",
            conversation_id="not.is.null",
            select="id,conversation_id,user_text,assistant_text:full_assistant_text,photo_attached,created_at",
            limit="1",
        )
        return ConversationMessage.model_validate(rows[0]) if rows else None

    def append(self, owner, session_id, row):
        self._client.check_patient(owner)
        self._client.request(
            "POST",
            "/rest/v1/rpc/append_thread_turn",
            body={"p_turn": {**row.model_dump(mode="json"), "session_id": str(session_id)}},
        )
        saved = self.message(owner, row.id)
        if saved is None:
            raise ValidationError("Saved message unavailable")
        return saved

    def fail(self, owner, turn_id):
        self._client.check_patient(owner)
        self._client.request("POST", "/rest/v1/rpc/fail_conversation_turn", body={"p_id": str(turn_id)})

    def clear(self, owner):
        self._client.check_patient(owner)
        # The existing clear RPC atomically clears both generations and recent text.
        self._client.request("POST", "/rest/v1/rpc/clear_conversation_history", body={})
