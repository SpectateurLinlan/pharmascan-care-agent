"""Opt-in loopback DEMO: normal activation/materialization before clock advances.

No debug/time/backfill HTTP endpoint is exposed. All fixtures are synthetic.
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from .assistant_enrollment_runtime import create_app as enrollment_app
from .conftest import FixedClock


def create_app():
    clock = FixedClock(datetime(2026, 10, 26, 12, 0, tzinfo=UTC))
    app = enrollment_app(clock=clock)
    client = TestClient(app)
    for language in ("en", "zh"):
        query = "client_id=DEMO-history-" + language

        def call(method, path, data, query=query):
            response = client.request(method, path + "?" + query, json=data)
            assert response.status_code == 200, response.text
            return response.json()

        session = call("POST", "/api/demo/start", {"client_id": "DEMO-history-" + language})
        call(
            "PUT",
            "/api/me/preferences",
            {"preferred_language": language, "voice_enabled": False, "tts_autoplay": False},
        )
        draft = call(
            "POST",
            "/api/medications/drafts",
            {
                "medication_name": "DEMO historical medicine",
                "dose_amount": 1,
                "dose_unit": "tablet",
                "frequency_kind": "daily",
                "frequency_local_times": ["20:00"],
            },
        )
        call("POST", f"/api/medications/drafts/{draft['source_id']}/review", {"field_ids": None})
        response = client.post(
            f"/api/medications/drafts/{draft['regimen_id']}/challenge?{query}&session_id={session['session_id']}",
            json={},
        )
        assert response.status_code == 200, response.text
        summary = response.json()
        call(
            "POST",
            "/api/medications/activate",
            {
                "regimen_id": draft["regimen_id"],
                **{
                    key: summary[key]
                    for key in ("challenge_id", "session_id", "session_state", "session_state_version")
                },
            },
        )
        due = client.get(f"/api/doses/due?{query}&regimen_id={draft['regimen_id']}")
        assert due.status_code == 200 and due.json()["occurrence_id"]
    client.close()
    clock.advance(hours=24)
    return app
