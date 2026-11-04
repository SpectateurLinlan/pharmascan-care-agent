"""Explicit loopback startup fixture; three synthetic reviewed plans via real APIs."""

import os
from datetime import UTC, datetime

from app.transport.app_factory import create_app
from app.transport.container import build_container
from fastapi.testclient import TestClient

from .conftest import FixedClock


def create_startup_app():
    if os.environ.get("MEDITHREAD_LOCAL_ACCEPTANCE") != "1":
        raise RuntimeError("This synthetic runtime requires explicit local acceptance opt-in")
    root = build_container(clock=FixedClock(datetime(2026, 10, 25, 0, tzinfo=UTC)))
    root.close_request()
    root.close_request = None
    root.medication_understanding = None  # No external knowledge/model integration in this timing fixture.
    app = create_app(container=root)
    with TestClient(app) as client:
        def call(method, path, body=None, **extra):
            response = client.request(method, path, params={"client_id": "DEMO-startup", **extra}, json=body)
            assert response.status_code == 200, (path, response.status_code)
            return response.json()

        for index in range(3):
            session = call("POST", "/api/demo/start", {"client_id": "DEMO-startup"})
            draft = call("POST", "/api/medications/drafts", {
                "medication_name": f"DEMO startup medicine {index + 1}", "dose_amount": 1, "dose_unit": "tablet",
                "frequency_kind": "daily", "frequency_local_times": ["08:00", "20:00"],
            })
            call("POST", f"/api/medications/drafts/{draft['source_id']}/review", {"field_ids": None})
            challenge = call("POST", f"/api/medications/drafts/{draft['regimen_id']}/challenge",
                             session_id=session["session_id"])
            call("POST", "/api/medications/activate", {
                key: challenge[key] for key in (
                    "regimen_id", "challenge_id", "session_id", "session_state", "session_state_version",
                )
            })
    return app
