"""DEMO_ONLY real HTTP + local PostgreSQL thread/RLS browser acceptance.

Auth/provider/business records are synthetic; thread messages use actual SQL RPCs.
Only the guarded localhost test database fixture is accepted. No .env is read.
"""

from contextlib import contextmanager
from threading import RLock

from app.agent.conversation import ConversationService
from app.agent.model_tools import ModelTools
from app.application.ai_quota import QuotaAgent
from app.application.conversation_threads import ConversationThreadService
from app.contracts.conversation_threads import ConversationMessage, ConversationSummary
from app.contracts.model import FunctionCall, ModelReply
from app.contracts.preferences import PreferenceUpdate
from app.infrastructure.memory_quota import MemoryQuota
from app.transport.app_factory import create_app
from app.transport.auth import AuthBoundary, StaticTokenVerifier
from app.transport.container import build_container
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from tests.backend.records_browser_server import OWNER, TOKEN, FixtureClock, FixtureIds
from tests.backend.test_conversation_threads_sql import db, owner


class SqlThreads:
    def __init__(self, connection, sessions):
        self.connection, self.sessions, self.lock = connection, sessions, RLock()

    @contextmanager
    def cursor(self, patient):
        with self.lock, owner(self.connection, patient):
            with self.connection.cursor(row_factory=dict_row) as cursor:
                yield cursor

    def create(self, patient, row):
        with self.cursor(patient) as c:
            c.execute("select public.create_conversation(%s,%s)", (row.id, row.title))

    def get(self, patient, identity):
        with self.cursor(patient) as c:
            row = c.execute(
                "select id,title,created_at,updated_at from public.conversations where id=%s", (identity,)
            ).fetchone()
            return ConversationSummary.model_validate(row) if row else None

    def list(self, patient, before, limit):
        with self.cursor(patient) as c:
            rows = c.execute(
                "select id,title,created_at,updated_at from public.conversations where has_messages "
                "order by updated_at desc,id desc"
            ).fetchall()
        values = [ConversationSummary.model_validate(row) for row in rows]
        start = next((i + 1 for i, row in enumerate(values) if row.id == before), 0) if before else 0
        return values[start : start + limit]

    def messages(self, patient, conversation, before, limit):
        with self.cursor(patient) as c:
            rows = c.execute(
                (
                    "select id,conversation_id,user_text,full_assistant_text as "
                    "assistant_text,photo_attached,created_at from public.conversation_turns where "
                    "conversation_id=%s order by created_at desc,id desc"
                ),
                (conversation,),
            ).fetchall()
        values = [ConversationMessage.model_validate(row) for row in rows]
        start = next((i + 1 for i, row in enumerate(values) if row.id == before), 0) if before else 0
        return values[start : start + limit]

    def claim(self, patient, conversation, identity, digest):
        with self.cursor(patient) as c:
            return c.execute(
                "select public.claim_conversation_turn(%s,%s,%s) as result", (conversation, identity, digest)
            ).fetchone()["result"]

    def message(self, patient, identity):
        with self.cursor(patient) as c:
            row = c.execute(
                (
                    "select id,conversation_id,user_text,full_assistant_text as "
                    "assistant_text,photo_attached,created_at from public.conversation_turns where id=%s"
                ),
                (identity,),
            ).fetchone()
            return ConversationMessage.model_validate(row) if row else None

    def append(self, patient, session_id, row):
        # Mirror only the synthetic runtime session; all durable writes use owned RPCs.
        with self.lock:
            self.connection.execute(
                (
                    "insert into "
                    "public.agent_sessions(id,patient_id,state,prompt_version,expires_at,conversation_id) "
                    "values(%s,%s,'collecting','DEMO_browser',now()+interval '2 hours',%s) on conflict(id) "
                    "do update set conversation_id=excluded.conversation_id"
                ),
                (session_id, patient, row.conversation_id),
            )
        with self.cursor(patient) as c:
            c.execute(
                "select public.append_thread_turn(%s)",
                (Jsonb({**row.model_dump(mode="json"), "session_id": str(session_id)}),),
            )
        return self.message(patient, row.id)

    def fail(self, patient, identity):
        with self.cursor(patient) as c:
            c.execute("select public.fail_conversation_turn(%s)", (identity,))

    def clear(self, patient):
        with self.cursor(patient) as c:
            c.execute("select public.clear_conversation_history()")


class DemoStatelessModel:
    """Test context plumbing only; explicitly no live Gemini or medical answer."""

    def create(self, **kwargs):
        import json

        history = kwargs["history"]
        initial = json.loads(history[0]["content"][0]["text"])
        text = "DEMO SIMULATED provider; no medical analysis."
        if initial["current_input"] == "DEMO A after reload":
            prior = [row["user"] for row in initial["context"]["recent_turns"]]
            assert "DEMO A second question" in prior
            assert "DEMO conversation B first question" not in prior
            if history[-1]["type"] != "function_result":
                return ModelReply(
                    calls=[FunctionCall(id="DEMO-fresh-read", name="list_active_medications", arguments={})]
                )
        return ModelReply(text=text)


if __name__ == "__main__":
    import uvicorn

    fixture = db.__wrapped__()
    connection = next(fixture)
    container = build_container(
        clock=FixtureClock(),
        ids=FixtureIds(),
        auth=AuthBoundary(mode="supabase", verifier=StaticTokenVerifier({TOKEN: {"sub": str(OWNER)}})),
    )
    container.preferences.save(OWNER, PreferenceUpdate(conversation_history_enabled=True))
    repository = SqlThreads(connection, container.orchestrator)
    # Public service/session contracts, same HTTP routes and Agent as the application.
    from app.infrastructure.memory_repos import InMemoryAgentSessionRepository

    container.conversation_threads = ConversationThreadService(
        repository, InMemoryAgentSessionRepository(container.store), container.clock, container.preferences
    )
    conversation = ConversationService(
        model=DemoStatelessModel(),
        tools=ModelTools(registry=container.registry, fallback=container.orchestrator),
        fallback=container.orchestrator,
        sessions=InMemoryAgentSessionRepository(container.store),
        ids=container.ids,
    )
    container.ai_agent = QuotaAgent(
        repository=MemoryQuota(clock=container.clock, nonce_factory=lambda: str(container.ids.new_id()), limit=200),
        conversation=conversation,
        fallback=container.orchestrator,
        daily_limit=200,
    )
    uvicorn.run(create_app(container), host="127.0.0.1", port=8767, log_level="warning")
