"""The local acceptance harness must fail closed before external traffic."""

from uuid import UUID

import httpx
from app.config import Settings
from app.contracts.conversation_threads import ConversationMessage
from app.contracts.preferences import PreferenceUpdate

from .workflow_support import WorkflowHarness


def test_default_harness_cannot_load_real_environment(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Settings.from_env must not be used by the offline harness")

    monkeypatch.setattr(Settings, "from_env", forbidden)
    monkeypatch.setenv("PERSISTENCE", "supabase")
    monkeypatch.setenv("MODEL_PROVIDER", "gemini")
    with WorkflowHarness() as h:
        response = h.client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["database"] == "simulated_in_memory"
        assert h.container.ai_agent is None


def test_default_harness_cannot_contact_real_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline harness attempted a real network transport")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    with WorkflowHarness() as h:
        result = h.container.medication_understanding.explain(
            patient_id=UUID(int=100), medication_name="ibuprofen", question="general_use"
        )
        assert result.general_knowledge.status == "no_reliable_match"
        assert result.general_knowledge.reason == "not_found"


def test_snapshot_exposes_real_saved_chat_instead_of_fabricating_an_empty_history():
    with WorkflowHarness() as h:
        h.container.conversation_history.append(
            h.owner_ids["A"], UUID(int=12), "DEMO-turn", "DEMO-private-history", "DEMO-answer"
        )
        assert h.snapshot()["history"][0]["user_text"] == "DEMO-private-history"


def test_upload_preserves_revision_and_source_kind_in_outgoing_request(monkeypatch):
    with WorkflowHarness() as h:
        monkeypatch.setattr(h, "view", lambda _: {"revision": 7})
        requests = []

        def request(method, path, **kwargs):
            built = httpx.Request(method, path, **kwargs)
            requests.append(built)
            return httpx.Response(200, json={})

        monkeypatch.setattr(h.client, "request", request)
        h.upload("DEMO-task", b"DEMO-image")
        assert dict(requests[0].url.params) == {
            "client_id": "DEMO-workflow-A", "expected_revision": "7", "source_kind": "pharmacy_label",
        }


def test_snapshot_includes_all_threads_and_all_pages_of_messages():
    with WorkflowHarness() as h:
        owner = h.owner_ids["A"]
        h.container.preferences.save(owner, PreferenceUpdate(conversation_history_enabled=True))
        service = h.container.conversation_threads
        for index in range(51):
            thread = service.create(owner, UUID(int=1000 + index), "DEMO-thread", False)
            for offset in range(101 if index == 0 else 1):
                message_id = UUID(int=10000 + index * 200 + offset)
                service.claim(owner, thread.id, message_id, f"DEMO-{message_id}")
                service.append(owner, UUID(int=500), ConversationMessage(
                    id=message_id, conversation_id=thread.id,
                    user_text="DEMO-private", assistant_text="DEMO-answer", created_at=h.clock.now(),
                ))
        assert len(h.snapshot()["history"]) == 151


def test_snapshot_includes_real_saved_workflow_state():
    with WorkflowHarness() as h:
        view = h.container.assistant_workflows.start(
            h.owner_ids["A"], "medication.enroll", UUID(h.workspace_id), None, {}, "allowed",
        )
        tasks = h.snapshot()["tasks"]
        assert len(tasks) == 1 and tasks[0]["id"] == str(view.task_id)
        assert tasks[0]["state"] == "choose_method"
