"""Opt-in release persistence check; synthetic owners, no visual/Push calls.

Real database confirmations use a current five-minute window. Multi-day B14
is tested separately with injected LOCAL time, never by backdating live rows.
"""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from tests.backend.test_supabase_live import create_live_harness

pytestmark = pytest.mark.skipif(os.environ.get("RUN_RELEASE_LIVE") != "1", reason="Release synthetic Supabase opt-in")


def test_release_persisted_reports_review_and_new_session():
    from app.transport.app_factory import create_app
    from app.transport.container import build_supabase_container

    settings, identities, clients, app, clock = create_live_harness()
    headers = {"Authorization": "Bearer " + identities[0].access_token}
    foreign = {"Authorization": "Bearer " + identities[1].access_token}
    clock.moment = datetime.now(UTC) - timedelta(minutes=5)
    base = clock.now()
    slots = [base + timedelta(minutes=index) for index in range(1, 5)]
    zone = ZoneInfo("Asia/Singapore")
    if len({row.astimezone(zone).date() for row in [base, *slots]}) != 1:
        pytest.skip("Current five-minute fixture crosses local midnight; rerun outside boundary")

    def call(method, path, body=None, **kwargs):
        response = app.request(method, path, headers=headers, json=body, **kwargs)
        assert response.status_code == 200, f"{path}: HTTP {response.status_code}"
        return response.json()

    start = call("POST", "/api/demo/start", {"client_id": "DEMO-release-live"})
    draft = call(
        "POST",
        "/api/medications/drafts",
        {
            "medication_name": "DEMO Release Review 500 mg",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_kind": "daily",
            "frequency_local_times": [row.astimezone(zone).strftime("%H:%M") for row in slots],
        },
    )
    call("POST", f"/api/medications/drafts/{draft['source_id']}/review", {"field_ids": None})
    activation = call(
        "POST", f"/api/medications/drafts/{draft['regimen_id']}/challenge", params={"session_id": start["session_id"]}
    )
    call(
        "POST",
        "/api/medications/activate",
        {
            key: activation[key]
            for key in ("regimen_id", "challenge_id", "session_id", "session_state", "session_state_version")
        },
    )
    for slot, status in zip(slots, ("taken", "not_taken", "unsure"), strict=False):
        clock.moment = slot + timedelta(seconds=2)
        due = call("GET", "/api/doses/due", params={"regimen_id": draft["regimen_id"]})
        assert due["occurrence_id"]
        path = f"/api/doses/{due['occurrence_id']}/report"
        body = {"regimen_id": draft["regimen_id"], "intake_status": status, "idempotency_key": "DEMO-" + uuid4().hex}
        assert app.post(path, headers=headers, json=body).status_code == 422
        pending = call("POST", path + "/challenge", body)
        assert app.post(path + "/challenge", headers=foreign, json=body).status_code == 404
        body["challenge_id"] = pending["challenge_id"]
        event = call("POST", path, body)
        assert call("POST", path, body)["event_id"] == event["event_id"]
    clock.moment = datetime.now(UTC)
    call("GET", "/api/doses/due", params={"regimen_id": draft["regimen_id"]})
    for days, value in ((3, 130), (1, 125)):
        call(
            "PUT",
            "/api/me/health-observations",
            {
                "id": str(uuid4()),
                "kind": "blood_pressure",
                "value": value,
                "secondary_value": 80,
                "unit": "mmHg",
                "description": "DEMO patient-entered review measurement",
                "occurred_at": (clock.now() - timedelta(days=days)).isoformat(),
                "confirmed": True,
            },
        )
    call(
        "POST",
        "/api/me/adherence-barriers",
        {
            "id": str(uuid4()),
            "category": "scheduling",
            "occurred_at": clock.now().isoformat(),
            "regimen_id": draft["regimen_id"],
            "description": "DEMO reporting around work was difficult",
            "chosen_action": "DEMO discuss schedule with pharmacist",
            "confirmed": True,
        },
    )
    stock_path = f"/api/me/inventory/{draft['medication_id']}"
    for kind, quantity in (("count", 2), ("refill", 30)):
        body = {
            "id": str(uuid4()),
            "kind": kind,
            "quantity": quantity,
            "unit": "tablet",
            "low_threshold": 7,
            "confirmed": True,
            "note": "DEMO confirmed supply",
        }
        first = call("POST", stock_path, body)
        assert call("POST", stock_path, body) == first
    task = call(
        "POST",
        "/api/me/care-tasks",
        {
            "id": str(uuid4()),
            "category": "medication_review",
            "title": "DEMO release pharmacist review",
            "due_at": (clock.now() + timedelta(days=1)).isoformat(),
            "medication_id": draft["medication_id"],
            "regimen_id": draft["regimen_id"],
            "notes": "DEMO patient-reported appointment",
            "confirmed": True,
        },
    )
    review = call("GET", "/api/me/medication-review", params={"days": 7})
    summary = review["summary"]
    assert (summary["reported_taken"], summary["reported_not_taken"], summary["unsure"]) == (1, 1, 1)
    assert (summary["medications"][0]["recorded_occurrences"], summary["medications"][0]["without_report"]) == (4, 1)
    assert review["trends"][0]["count"] == 2 and review["trends"][0]["change"] == -5
    assert len(call("GET", stock_path)["transactions"]) == 2
    assert not clients[1].rows("dose_events") and not clients[1].rows("inventory_transactions")
    events = clients[0].rows("dose_events")
    assert len(events) == 3 and all(not row["ingestion_proven"] for row in events)
    assert all(row["confirmation_challenge_id"] for row in events)
    # Fresh composition root and transport reread the remote owner records.
    fresh = TestClient(
        create_app(container=build_supabase_container(settings=settings, clock=clock)), raise_server_exceptions=False
    )
    assert fresh.get("/api/me/medication-review", headers=headers, params={"days": 7}).json() == review
    assert fresh.get("/api/me/medication-review", headers=foreign).json()["follow_ups"] == []
    evidence = {
        "demo_only": True,
        "classification": "SUPABASE LIVE VERIFIED",
        "dose_window": "current five minutes; NOT multi-day live B14",
        "summary": summary,
        "review": review,
        "event_count": len(events),
        "new_application_read_identical": True,
        "foreign_owner_empty": True,
    }
    target = Path("outputs/session05")
    target.mkdir(parents=True, exist_ok=True)
    artifact = target / "live-review.json"
    artifact.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.environ.get("RUN_RELEASE_GEMINI") == "1":
        model_settings = replace(settings, model_provider="gemini")
        model_app = TestClient(
            create_app(container=build_supabase_container(settings=model_settings, clock=clock)),
            raise_server_exceptions=False,
        )
        started = model_app.post("/api/demo/start", headers=headers, json={"client_id": "DEMO-release-fresh-agent"})
        assert started.status_code == 200
        answer = model_app.post(
            "/api/agent/messages",
            headers=headers,
            json={
                "session_id": started.json()["session_id"],
                "client_turn_id": "DEMO-" + uuid4().hex,
                "text": "I am seeing my pharmacist tomorrow. Read my medication review records for this week, "
                "reported taken/not taken/unsure versus unrecorded doses, symptoms or measurements, "
                "barriers, inventory and unresolved follow-ups. Help me prepare without changing my plan.",
            },
        )
        assert answer.status_code == 200
        payload = answer.json()
        evidence["agent"] = {key: payload[key] for key in ("mode", "message", "tool_traces")}
        artifact.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        assert payload["mode"] == "gemini", "Provider failed; do not report Gemini live verification"
        assert any(
            row["tool_name"] == "get_long_term_care" and row["payload"].get("action") == "prepare_medication_review"
            for row in payload["tool_traces"]
        )
        assert task["title"] in payload["message"]
        assert not payload["pending_report"] and not payload["care_request"]
        assert len(clients[0].rows("dose_events")) == 3
    evidence["all_assertions_passed"] = True
    artifact.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
