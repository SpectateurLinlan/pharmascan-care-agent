"""REAL model + Auth/application/RLS, explicit opt-in and synthetic records."""

import os
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from app.config import Settings
from app.infrastructure.supabase_data import SupabaseDataClient
from app.transport.app_factory import create_app
from app.transport.container import build_supabase_container
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(os.environ.get("RUN_GEMINI_LIVE") != "1", reason="REAL Gemini opt-in required")


def test_real_gemini_context_tools_uncertainty_and_b14():
    settings = replace(Settings.from_env(), model_provider="gemini", auth_mode="supabase", persistence="supabase")
    with httpx.Client(timeout=15) as client:
        signup = client.post(
            settings.require_supabase_url() + "/auth/v1/signup",
            headers={"apikey": settings.require_publishable_key()},
            json={"data": {"demo_only": True}},
        )
        assert signup.status_code == 200
        data = signup.json()
        assert bool(data.get("access_token"))
    from uuid import UUID

    patient = UUID(data["user"]["id"])
    headers = {"Authorization": "Bearer " + data["access_token"]}
    db = SupabaseDataClient(
        base_url=settings.require_supabase_url(),
        publishable_key=settings.require_publishable_key(),
        access_token=data["access_token"],
        patient_id=patient,
    )
    app = TestClient(create_app(container=build_supabase_container(settings=settings)), raise_server_exceptions=False)

    def call(method, path, **kwargs):
        response = app.request(method, path, headers=headers, **kwargs)
        assert response.status_code == 200, f"HTTP {response.status_code} for {path}"
        return response.json()

    session = call("POST", "/api/demo/start", json={"client_id": "DEMO-real-gemini"})
    draft = call(
        "POST",
        "/api/medications/drafts",
        json={
            "medication_name": "DEMO Metformin",
            "dose_amount": 500,
            "dose_unit": "mg",
            "frequency_kind": "daily",
            "frequency_local_times": ["20:00"],
        },
    )
    call("POST", f"/api/medications/drafts/{draft['source_id']}/review", json={"field_ids": None})
    activation = call(
        "POST", f"/api/medications/drafts/{draft['regimen_id']}/challenge", params={"session_id": session["session_id"]}
    )
    call(
        "POST",
        "/api/medications/activate",
        json={
            key: activation[key]
            for key in ["regimen_id", "challenge_id", "session_id", "session_state", "session_state_version"]
        },
    )

    def ask(text):
        answer = call(
            "POST",
            "/api/agent/messages",
            json={"session_id": session["session_id"], "client_turn_id": "DEMO-" + uuid4().hex, "text": text},
        )
        assert answer["mode"] == "gemini", "Real provider path did not complete; do not claim live model success"
        return answer

    tonight = ask("What medicine should I take tonight?")
    assert "DEMO Metformin" in tonight["message"] and "20:00" in tonight["message"]
    assert any(row["tool_name"] == "check_due_dose" for row in tonight["tool_traces"])
    status = ask("Did I already take it?")
    assert any(row["tool_name"] == "get_dose_status" for row in status["tool_traces"])
    assert not db.rows("dose_events")
    uncertain = ask("I'm not sure whether I took it.")
    assert not uncertain["pending_report"] and not db.rows("dose_events")
    report = ask("I took it.")
    assert report["requires_confirmation"] and report["pending_report"] and not db.rows("dose_events")
    pending = report["pending_report"]
    body = {
        "regimen_id": pending["regimen_id"],
        "intake_status": pending["summary"]["intake_status"],
        "idempotency_key": pending["idempotency_key"],
        "challenge_id": pending["challenge_id"],
    }
    saved = call("POST", f"/api/doses/{pending['occurrence_id']}/report", json=body)
    repeated = call("POST", f"/api/doses/{pending['occurrence_id']}/report", json=body)
    assert saved["event_id"] == repeated["event_id"] and len(db.rows("dose_events")) == 1
    call("PUT", "/api/me/preferences", json={"preferred_language": "zh"})
    chinese = ask("\u4eca\u665a\u6211\u5e94\u8be5\u67e5\u770b\u4ec0\u4e48\u7528\u836f\u5b89\u6392\uff1f")
    assert any("\u4e00" <= char <= "\u9fff" for char in chinese["message"])
    usage = call("GET", "/api/agent/usage")
    assert usage["llm_user_turns"] == 5 and usage["model_requests"] >= 5 and usage["limit"] == 20
