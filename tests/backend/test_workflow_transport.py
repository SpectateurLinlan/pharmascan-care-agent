"""DEMO_ONLY new/legacy HTTP share the same message and ownership boundary."""

import json
from uuid import uuid4

from app.contracts.preferences import PreferenceUpdate
from app.transport.app_factory import create_app
from app.transport.container import build_container
from fastapi.testclient import TestClient


def test_http_start_fields_view_and_foreign_owner_are_checked(workflow):
    h = workflow
    first = h.start("medication.enroll")
    assert first["state"] == "choose_method"
    assert {x["value"] for x in first["actions"][0]["options"]} == {"manual", "photo"}
    updated = h.event(first["task_id"], "choose_method", {"method": "manual"})
    assert updated["revision"] == 2 and h.view(first["task_id"]) == updated
    foreign = h.client.get(f"/api/agent/workflows/tasks/{first['task_id']}", params={"client_id": "DEMO-workflow-B"})
    assert foreign.status_code == 404
    unauthenticated = h.client.get(f"/api/agent/workflows/tasks/{first['task_id']}")
    assert unauthenticated.status_code == 401


def test_saved_start_replay_is_exact_and_cannot_rebind_values(workflow):
    h = workflow
    payload = {
        "capability_id": "medication.enroll",
        "workspace_id": h.workspace_id,
        "values": {},
        "client_event_id": str(uuid4()),
    }
    first = h._request("POST", "/api/agent/workflows/tasks", json=payload)
    h.event(first["task_id"], "choose_method", {"method": "manual"})
    assert h._request("POST", "/api/agent/workflows/tasks", json=payload) == first
    conflict = h.client.post(
        "/api/agent/workflows/tasks",
        params={"client_id": "DEMO-workflow-A"},
        json={**payload, "values": {"method": "photo"}},
    )
    assert conflict.status_code == 409 and len(h.snapshot()["tasks"]) == 1


def test_manifest_disabled_and_persistence_unavailable_never_advertise_success():
    c = build_container()
    try:
        with TestClient(create_app(c)) as client:
            response = client.get("/api/agent/workflows/capabilities", params={"client_id": "DEMO-disabled"})
            assert response.status_code == 200
            assert response.json()["contract_version"] == 1
            assert not response.json()["enabled"] and not any(x["available"] for x in response.json()["capabilities"])
    finally:
        if c.close_request:
            c.close_request()


def test_new_message_can_start_workflow_and_legacy_message_still_works(workflow):
    h = workflow
    reply = h._request(
        "POST",
        "/api/agent/workflows/messages",
        json={
            "text": "我想添加一种药物",
            "workspace_id": h.workspace_id,
            "conversation_id": None,
            "client_turn_id": str(uuid4()),
        },
    )
    assert reply["workflow"]["state"] == "choose_method"
    assert reply["reply"]["mode"] == "workflow"
    legacy = h._request(
        "POST", "/api/agent/messages", json={"text": "List my medications", "client_turn_id": "DEMO-old"}
    )
    assert "workflow" not in legacy and legacy["session_id"]


def test_http_ephemeral_message_does_not_save_thread_title_context_or_claim_digest(workflow):
    h = workflow
    h.container.preferences.save(h.owner_ids["A"], PreferenceUpdate(conversation_history_enabled=True))
    secret = "DEMO-private-http-no-save"
    first = h.start("medication.enroll", save=False)
    reply = h._request(
        "POST",
        "/api/agent/workflows/messages",
        json={
            "text": "Check application data: " + secret,
            "workspace_id": h.workspace_id,
            "conversation_id": None,
            "client_turn_id": str(uuid4()),
            "task_id": first["task_id"],
            "expected_revision": first["revision"],
            "ephemeral": {"capability_id": "medication.enroll", "fields": {"medication_name": secret}},
        },
    )
    assert not reply["reply"]["history_saved"] and reply["reply"]["conversation_id"] is None
    assert not h.snapshot()["history"] and secret not in json.dumps(h.snapshot())
    assert not h.container.conversation_threads.list(h.owner_ids["A"]).entries


def test_lost_new_workflow_message_response_recovers_task_without_second_start(workflow):
    h = workflow
    h.container.preferences.save(h.owner_ids["A"], PreferenceUpdate(conversation_history_enabled=True))
    payload = {
        "text": "Add a medication",
        "workspace_id": h.workspace_id,
        "conversation_id": None,
        "client_turn_id": str(uuid4()),
    }
    first = h._request("POST", "/api/agent/workflows/messages", json=payload)
    duplicate = h._request("POST", "/api/agent/workflows/messages", json=payload)
    assert duplicate["workflow"]["task_id"] == first["workflow"]["task_id"]
    assert len(h.snapshot()["tasks"]) == 1 and len(h.snapshot()["history"]) == 1
    assert not duplicate["reply"]["requires_confirmation"]


def test_independent_knowledge_question_suspends_incomplete_task_without_losing_fields(workflow):
    h = workflow
    first = h.start("medication.enroll", {"method": "manual", "medication_name": "DEMO-original"})
    response = h._request(
        "POST",
        "/api/agent/workflows/messages",
        json={
            "text": "What is ibuprofen?",
            "workspace_id": h.workspace_id,
            "task_id": first["task_id"],
            "expected_revision": first["revision"],
            "client_turn_id": str(uuid4()),
        },
    )
    assert response["workflow"]["state"] == "suspended"
    assert h.view(first["task_id"])["visible_fields"]["medication_name"] == "DEMO-original"
