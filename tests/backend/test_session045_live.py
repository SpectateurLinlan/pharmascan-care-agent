"""Opt-in real Auth/JWT/RLS/metadata/history; no Gemini, Stage2 or speech calls."""

import os
from uuid import uuid4

import pytest
from app.domain.errors import AuthenticationRequiredError, ValidationError

from tests.backend.test_supabase_live import create_live_harness

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SESSION045_LIVE") != "1", reason="Session04.5 synthetic Supabase live opt-in"
)


def test_history_consent_owner_pagination_and_reviewed_dose_basis_persist():
    settings, identities, clients, app, clock = create_live_harness()
    a, b = identities
    ah = {"Authorization": "Bearer " + a.access_token}
    bh = {"Authorization": "Bearer " + b.access_token}

    def call(method, path, body=None, headers=None):
        response = app.request(method, path, json=body, headers=headers or ah)
        assert response.status_code == 200, f"HTTP {response.status_code} for {path}"
        return response.json()

    session = call("POST", "/api/demo/start", {"client_id": "DEMO-S045"})
    call(
        "POST",
        "/api/agent/messages",
        {"session_id": session["session_id"], "text": "DEMO hello", "client_turn_id": "not-saved"},
    )
    assert call("GET", "/api/agent/history")["entries"] == []
    call("PUT", "/api/me/preferences", {"conversation_history_enabled": True})
    for index in range(2):
        assert call(
            "POST",
            "/api/agent/messages",
            {"session_id": session["session_id"], "text": f"DEMO hello {index}", "client_turn_id": f"saved-{index}"},
        )["history_saved"]
    first = call("GET", "/api/agent/history?limit=1")
    assert len(first["entries"]) == 1 and first["next_before"]
    second = call("GET", "/api/agent/history?limit=1&before=" + first["next_before"])
    assert len(second["entries"]) == 1
    assert first["entries"][0]["id"] != second["entries"][0]["id"]
    assert call("GET", "/api/agent/history", headers=bh)["entries"] == []
    assert clients[1].rows("conversation_turns") == []
    assert app.get("/api/agent/history?before=" + first["next_before"], headers=bh).status_code == 404
    with pytest.raises((AuthenticationRequiredError, ValidationError)):
        clients[1].request(
            "POST",
            "/rest/v1/rpc/append_conversation_turn",
            body={
                "p_turn": {
                    "id": str(uuid4()),
                    "patient_id": str(a.user_id),
                    "session_id": session["session_id"],
                    "user_text": "DEMO forged",
                    "assistant_text": "DEMO",
                }
            },
        )
    metadata = {
        "strength_text": "500 mg",
        "form": "tablet",
        "formulation": "standard",
        "single_ingredient": True,
        "instructions_text": "Take 1 tablet daily",
        "patient_checked": True,
    }
    draft = call(
        "POST",
        "/api/medications/drafts",
        {
            "medication_name": "DEMO S045 Metformin",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_kind": "daily",
            "frequency_local_times": ["20:00"],
            "dose_basis": metadata,
        },
    )
    source = clients[0].rows("source_documents", id="eq." + draft["source_id"])[0]
    assert source["dose_basis"] == metadata
    assert clients[1].rows("source_documents", id="eq." + draft["source_id"]) == []
    call("POST", f"/api/medications/drafts/{draft['source_id']}/review", {"field_ids": None})
    with pytest.raises((AuthenticationRequiredError, ValidationError)):
        clients[0].request(
            "PATCH",
            "/rest/v1/source_documents",
            params={"id": "eq." + draft["source_id"]},
            body={"dose_basis": {**metadata, "strength_text": "1000 mg"}},
        )
    challenge = call(
        "POST", f"/api/medications/drafts/{draft['regimen_id']}/challenge?session_id={session['session_id']}"
    )
    call(
        "POST",
        "/api/medications/activate",
        {
            key: challenge[key]
            for key in ["regimen_id", "challenge_id", "session_id", "session_state", "session_state_version"]
        },
    )
    assert call("GET", "/api/me/medications")["medications"][0]["dose_basis"] == metadata
    assert clients[0].rows("dose_events") == []
    assert app.request("DELETE", "/api/agent/history", headers=ah, json={"confirmed": False}).status_code == 422
    call("DELETE", "/api/agent/history", {"confirmed": True})
    assert call("GET", "/api/agent/history")["entries"] == []
    assert call("GET", "/api/me/medications")["item_count"] == 1
    assert clients[0].rows("agent_sessions", id="eq." + session["session_id"])[0]["context"]["recent_turns"] == []
