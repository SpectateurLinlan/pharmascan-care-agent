"""Release Scenario D: real Application HTTP/B14, SIMULATED persistence/time.

No final state is inserted into repositories. Every clinical write uses the
same reviewed-source and explicit-confirmation endpoints as the patient UI.
"""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.backend.test_transport import FixedClock


def prepare_review_timeline(client: TestClient, clock: FixedClock) -> dict:
    """Build five synthetic days via public APIs; leave one dose unrecorded."""

    def call(method, path, body=None, **kwargs):
        params = {"client_id": "DEMO-release-D", **kwargs.pop("params", {})}
        response = client.request(method, path, params=params, json=body, **kwargs)
        assert response.status_code == 200, f"{path}: {response.status_code} {response.text}"
        return response.json()

    start = call("POST", "/api/demo/start", {"client_id": "DEMO-release-D"})
    draft = call(
        "POST",
        "/api/medications/drafts",
        {
            "medication_name": "DEMO Review Metformin 500 mg",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_kind": "daily",
            "frequency_local_times": ["08:00"],
            "course_start_date": "2026-10-13",
        },
    )
    call("POST", f"/api/medications/drafts/{draft['source_id']}/review", {"field_ids": None})
    # session_id is a query parameter, not part of the activation request body.
    response = client.post(
        f"/api/medications/drafts/{draft['regimen_id']}/challenge",
        params={"client_id": "DEMO-release-D", "session_id": start["session_id"]},
    )
    assert response.status_code == 200
    challenge = response.json()
    call(
        "POST",
        "/api/medications/activate",
        {
            key: challenge[key]
            for key in ("regimen_id", "challenge_id", "session_id", "session_state", "session_state_version")
        },
    )
    inventory = f"/api/me/inventory/{draft['medication_id']}"
    count = {
        "id": str(uuid4()),
        "kind": "count",
        "quantity": 10,
        "unit": "tablet",
        "low_threshold": 7,
        "confirmed": True,
        "note": "DEMO physical count",
    }
    call("POST", inventory, count)
    event_ids = []
    for day, status in enumerate(("taken", "not_taken", "unsure", None, "taken")):
        clock.advance(days=1 if day else 0, hours=0 if day else 2)
        due = client.get("/api/doses/due", params={"client_id": "DEMO-release-D", "regimen_id": draft["regimen_id"]})
        assert due.status_code == 200
        # History materialises today's schedule. Select by due date, since the
        # due lookup may correctly offer yesterday's unrecorded dose first.
        history = client.get(
            "/api/me/dose-history", params={"client_id": "DEMO-release-D", "regimen_id": draft["regimen_id"]}
        ).json()
        today = clock.now().date().isoformat()
        occurrence = next(row for row in history["entries"] if row["due_at"].startswith(today))
        if status is not None:
            path = f"/api/doses/{occurrence['occurrence_id']}/report"
            body = {
                "regimen_id": draft["regimen_id"],
                "intake_status": status,
                "idempotency_key": f"DEMO-release-day-{day}",
            }
            assert client.post(path, params={"client_id": "DEMO-release-D"}, json=body).status_code == 422
            pending = call("POST", path + "/challenge", body)
            body["challenge_id"] = pending["challenge_id"]
            saved = call("POST", path, body)
            assert call("POST", path, body)["event_id"] == saved["event_id"]
            event_ids.append(saved["event_id"])
        call(
            "PUT",
            "/api/me/health-observations",
            {
                "id": str(uuid4()),
                "kind": "blood_pressure",
                "value": 130 - day,
                "secondary_value": 80,
                "unit": "mmHg",
                "description": "DEMO measured for review",
                "occurred_at": clock.now().isoformat(),
                "confirmed": True,
            },
        )
    barrier = call(
        "POST",
        "/api/me/adherence-barriers",
        {
            "id": str(uuid4()),
            "category": "scheduling",
            "occurred_at": clock.now().isoformat(),
            "regimen_id": draft["regimen_id"],
            "description": "DEMO work schedule made reporting difficult",
            "chosen_action": "DEMO discuss timing with pharmacist",
            "confirmed": True,
        },
    )
    call("POST", inventory, {**count, "id": str(uuid4()), "kind": "refill", "quantity": 30})
    task = call(
        "POST",
        "/api/me/care-tasks",
        {
            "id": str(uuid4()),
            "category": "medication_review",
            "title": "DEMO pharmacist review",
            "due_at": (clock.now() + timedelta(days=2)).isoformat(),
            "medication_id": draft["medication_id"],
            "regimen_id": draft["regimen_id"],
            "notes": "DEMO patient-reported appointment",
            "confirmed": True,
        },
    )
    clock.advance(minutes=1)
    call("POST", "/api/demo/start", {"client_id": "DEMO-release-D"})
    review = call("GET", "/api/me/medication-review", params={"days": 7})
    return {"draft": draft, "review": review, "task": task, "barrier": barrier, "event_ids": event_ids}


def test_scenario_d_five_days_public_api_b14_and_review():
    from app.transport.app_factory import create_app
    from app.transport.container import build_container

    clock = FixedClock(datetime(2026, 10, 12, 23, tzinfo=UTC))
    container = build_container(clock=clock)
    with TestClient(create_app(container), raise_server_exceptions=False) as client:
        data = prepare_review_timeline(client, clock)
        review = data["review"]
        assert review["timezone"] == "Asia/Singapore"
        summary = review["summary"]
        assert (summary["reported_taken"], summary["reported_not_taken"], summary["unsure"]) == (2, 1, 1)
        medicine = summary["medications"][0]
        assert (medicine["recorded_occurrences"], medicine["without_report"]) == (5, 1)
        assert "unrecorded is not missed" in review["adherence_denominator"]
        assert review["trends"][0]["count"] == 5 and review["trends"][0]["change"] == -4
        assert review["barriers"][0]["id"] == data["barrier"]["id"]
        assert review["follow_ups"][0]["id"] == data["task"]["id"]
        assert review["source_records"][0]["source_document_id"] == data["draft"]["source_id"]
        assert review["source_records"][0]["patient_review_is_professional_verification"] is False
        # Recreate transport with the SAME test persistence, not precomputed
        # summary text. This is not a durable database/restart verification.
        with TestClient(create_app(container), raise_server_exceptions=False) as fresh:
            again = fresh.get("/api/me/medication-review", params={"client_id": "DEMO-release-D", "days": 7})
            assert again.json() == review
            foreign = fresh.get("/api/me/medication-review", params={"client_id": "DEMO-other"})
            assert foreign.json()["summary"]["medications"] == []


def create_review_test_app():
    """Explicit local-only browser fixture factory; no real providers or DB.

    Allows reproducing release-review.spec.ts from public files alone. This
    factory is not a production entrypoint and refuses accidental invocation.
    """
    from app.transport.app_factory import create_app
    from app.transport.container import build_container

    if os.environ.get("RUN_RELEASE_BROWSER") != "1":
        raise RuntimeError("RUN_RELEASE_BROWSER=1 is required for the LOCAL synthetic fixture")
    app = create_app(build_container(clock=FixedClock()))
    with TestClient(app, raise_server_exceptions=False) as client:
        prepare_review_timeline(client, app.state.container.clock)
    return app


def test_browser_fixture_is_explicit_and_serves_the_application_review(monkeypatch):
    monkeypatch.delenv("RUN_RELEASE_BROWSER", raising=False)
    with pytest.raises(RuntimeError, match="LOCAL synthetic fixture"):
        create_review_test_app()
    monkeypatch.setenv("RUN_RELEASE_BROWSER", "1")
    with TestClient(create_review_test_app()) as client:
        review = client.get("/api/me/medication-review", params={"client_id": "DEMO-release-D", "days": 7}).json()
        assert (
            review["summary"]["reported_taken"],
            review["summary"]["reported_not_taken"],
            review["summary"]["unsure"],
        ) == (2, 1, 1)
