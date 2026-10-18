"""DEMO_ONLY HTTP lifecycle/safety; memory adapter, real services and tools."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.agent.conversation import ConversationService
from app.agent.model_tools import ModelTools
from app.agent.orchestrator import AgentTurn
from app.contracts.agent_context import AgentContext, RecentTurn
from app.contracts.context_bounds import bounded_context
from app.contracts.model import ModelReply
from app.infrastructure.memory_repos import InMemoryAgentSessionRepository
from app.transport.app_factory import create_app
from app.transport.auth import AuthBoundary, StaticTokenVerifier
from app.transport.container import build_container
from fastapi.testclient import TestClient

A = "d00d0000-0000-4000-8000-000000000001"
B = "d00d0000-0000-4000-8000-000000000002"


class Clock:
    def __init__(self):
        self.moment = datetime(2026, 10, 17, 15, 59, tzinfo=UTC)

    def now(self):
        return self.moment

    def advance(self):
        self.moment += timedelta(minutes=2)


def wired():
    c = build_container(
        clock=Clock(),
        auth=AuthBoundary(mode="supabase", verifier=StaticTokenVerifier({"DEMO-A": {"sub": A}, "DEMO-B": {"sub": B}})),
    )
    return c, TestClient(create_app(c))


def send(client, text, conversation=None, session=None, key=None, token="DEMO-A"):
    return client.post(
        "/api/agent/messages",
        headers={"Authorization": "Bearer " + token},
        json={
            "conversation_id": conversation,
            "text": text,
            "session_id": session,
            "client_turn_id": key or str(uuid4()),
        },
    )


def consent(client, enabled):
    response = client.put(
        "/api/me/preferences",
        headers={"Authorization": "Bearer DEMO-A"},
        json={"conversation_history_enabled": enabled},
    )
    assert response.status_code == 200


def test_a_b_resume_isolation_opt_out_and_duplicate_does_not_reexecute():
    c, client = wired()
    consent(client, True)
    headers = {"Authorization": "Bearer DEMO-A"}
    a = send(client, "DEMO A text", key="DEMO-first").json()
    aid = a["conversation_id"]
    assert aid
    duplicate = send(client, "DEMO A text", key="DEMO-first").json()
    assert duplicate["conversation_id"] == aid
    assert not duplicate["requires_confirmation"] and duplicate["tool_traces"] == []
    b = send(client, "DEMO B text").json()
    bid = b["conversation_id"]
    assert bid != aid
    assert len(client.get("/api/agent/conversations", headers=headers).json()["entries"]) == 2
    resumed = client.post(f"/api/agent/conversations/{aid}/resume", headers=headers).json()
    assert resumed["session_id"] != a["session_id"]
    session = c.orchestrator.get_session(patient_id=UUID(A), session_id=UUID(resumed["session_id"]))
    assert session.context.referenced_medication_id is None and session.state == "collecting"
    assert [row.user for row in session.context.recent_turns] == ["DEMO A text"]
    continued = send(client, "DEMO A continued", aid, resumed["session_id"]).json()
    assert continued["conversation_id"] == aid
    assert len(client.get(f"/api/agent/conversations/{aid}", headers=headers).json()["entries"]) == 2
    assert len(client.get(f"/api/agent/conversations/{bid}", headers=headers).json()["entries"]) == 1
    assert client.get(f"/api/agent/conversations/{aid}", headers={"Authorization": "Bearer DEMO-B"}).status_code == 404
    assert (
        client.post(f"/api/agent/conversations/{aid}/resume", headers={"Authorization": "Bearer DEMO-B"}).status_code
        == 404
    )
    assert send(client, "DEMO foreign", aid, token="DEMO-B").status_code == 404
    assert send(client, "DEMO mismatch", aid, b["session_id"]).status_code == 422
    consent(client, False)
    temp = send(client, "DEMO not saved").json()
    assert temp["conversation_id"] is None and temp["history_saved"] is None
    send(client, "DEMO unsaved continuation", aid, continued["session_id"])
    assert len(client.get(f"/api/agent/conversations/{aid}", headers=headers).json()["entries"]) == 2
    assert client.request("DELETE", "/api/agent/history", headers=headers, json={"confirmed": True}).status_code == 200
    assert client.get("/api/agent/conversations", headers=headers).json()["entries"] == []


def test_restored_text_enters_stateless_model_context_without_confirmations_or_b_context():
    c, client = wired()
    consent(client, True)
    headers = {"Authorization": "Bearer DEMO-A"}
    a = send(client, "DEMO topic A").json()
    send(client, "DEMO topic B")
    resumed = client.post(f"/api/agent/conversations/{a['conversation_id']}/resume", headers=headers).json()
    captured = []

    class Model:
        def create(self, **kwargs):
            captured.append(kwargs["history"])
            return ModelReply(text="DEMO model")

    service = ConversationService(
        model=Model(),
        tools=ModelTools(registry=c.registry, fallback=c.orchestrator),
        fallback=c.orchestrator,
        sessions=InMemoryAgentSessionRepository(c.store),
        ids=c.ids,
    )
    from uuid import UUID

    service.handle_turn(
        patient_id=UUID(A), session_id=UUID(resumed["session_id"]), turn=AgentTurn(text="What did I mention?")
    )
    encoded = json.dumps(captured)
    assert "DEMO topic A" in encoded and "DEMO topic B" not in encoded
    assert "pending_report" not in encoded and "challenge_id" not in encoded


def test_bounded_restore_does_not_delete_full_history_or_reset_thread_at_midnight():
    c, client = wired()
    consent(client, True)
    headers = {"Authorization": "Bearer DEMO-A"}
    a = send(client, "DEMO first").json()
    c.clock.advance()
    for i in range(8):
        response = send(client, "DEMO " + str(i) + " 合成文本" * 100, a["conversation_id"], a["session_id"])
        assert response.status_code == 200
    entries = client.get(f"/api/agent/conversations/{a['conversation_id']}", headers=headers).json()["entries"]
    assert len(entries) == 9
    restored = client.post(f"/api/agent/conversations/{a['conversation_id']}/resume", headers=headers).json()
    from uuid import UUID

    context = c.orchestrator.get_session(patient_id=UUID(A), session_id=UUID(restored["session_id"])).context
    assert len(context.recent_turns) <= 6
    maximum = bounded_context(
        AgentContext(recent_turns=[RecentTurn(user="患" * 500, assistant="答" * 700) for _ in range(6)])
    )
    assert len(json.dumps(maximum.model_dump(mode="json"), ensure_ascii=False).encode()) < 20000
    assert len(client.get(f"/api/agent/conversations/{a['conversation_id']}", headers=headers).json()["entries"]) == 9


def test_threaded_photo_keeps_raw_words_and_presence_only_and_opt_out_has_no_rows():
    from tests.backend.test_chat_photo_boundary import evidence

    c, client = wired()
    headers = {"Authorization": "Bearer DEMO-A"}
    for enabled in (True, False):
        consent(client, enabled)
        response = client.post(
            "/api/agent/messages",
            headers=headers,
            json={
                "conversation_id": None,
                "text": "合成患者原话 DEMO",
                "client_turn_id": str(uuid4()),
                "photo_context": evidence(),
            },
        )
        assert response.status_code == 200
        reply = response.json()
        if enabled:
            page = client.get(f"/api/agent/conversations/{reply['conversation_id']}", headers=headers).json()
            assert page["entries"][0]["user_text"] == "合成患者原话 DEMO"
            assert page["entries"][0]["photo_attached"] is True
            assert "DEMO_INTERNAL_OCR_ONLY" not in json.dumps(page)
        else:
            assert reply["conversation_id"] is None and reply["history_saved"] is None
    assert len(client.get("/api/agent/conversations", headers=headers).json()["entries"]) == 1
    assert not c.store.events


def test_expired_runtime_renews_inside_same_durable_thread():
    c, client = wired()
    consent(client, True)
    first = send(client, "DEMO before expiry").json()
    c.clock.moment += timedelta(days=2)
    response = send(client, "DEMO after expiry", first["conversation_id"], first["session_id"])
    assert response.status_code == 200
    second = response.json()
    assert second["conversation_id"] == first["conversation_id"]
    assert second["session_id"] != first["session_id"]
    session = c.orchestrator.get_session(patient_id=UUID(A), session_id=UUID(second["session_id"]))
    assert any(row.user == "DEMO before expiry" for row in session.context.recent_turns)


def test_navigation_context_requires_owned_ids_and_uses_server_name():
    c, client = wired()
    headers = {"Authorization": "Bearer DEMO-A"}
    assert (
        client.post(
            "/api/agent/navigation-context",
            headers=headers,
            json={
                "page": "medicine-detail",
                "medication_id": str(uuid4()),
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/agent/navigation-context",
            headers=headers,
            json={
                "page": "medicine-detail",
                "display_name": "DEMO untrusted name",
            },
        ).status_code
        == 422
    )
    assert client.post("/api/agent/navigation-context", headers=headers, json={"page": "records"}).json() == {
        "page": "records",
        "medication_id": None,
        "regimen_id": None,
        "display_name": None,
    }
