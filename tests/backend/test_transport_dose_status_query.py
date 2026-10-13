"""HTTP integration tests for the "Have I taken X?" question (Session 3A item 3).

** SIMULATED ** persistence (in-memory fakes; B02) but a real ASGI app: the
route genuinely dispatches, the orchestrator genuinely plans, the registry
genuinely executes and the error mapper genuinely applies.

This locks in the repair of an observed product defect: the chat endpoint used
to answer a dose-status question with "You have 1 active medication(s)."
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.transport.app_factory import create_app  # noqa: E402
from app.transport.container import build_container  # noqa: E402

FIXED_NOW = datetime(2026, 10, 12, 23, 0, tzinfo=UTC)  # 2026-10-13 07:00 Asia/Singapore
CLIENT = "tab-dsq"


class FixedClock:
    def __init__(self, moment: datetime = FIXED_NOW) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment

    def advance(self, **kwargs: float) -> None:
        self._moment = self._moment + timedelta(**kwargs)


class CountingIdGenerator:
    OFFSET = 1 << 96

    def __init__(self, start: int = 1) -> None:
        self._next = start

    def new_id(self) -> UUID:
        value = self.OFFSET + self._next
        self._next += 1
        return UUID(int=value)


@pytest.fixture()
def clock() -> FixedClock:
    return FixedClock()


@pytest.fixture()
def client(clock: FixedClock) -> TestClient:
    container = build_container(clock=clock, ids=CountingIdGenerator())
    return TestClient(create_app(container), raise_server_exceptions=False)


def _params(**extra: object) -> dict[str, object]:
    return {"client_id": CLIENT, **extra}


def _activate_daily(client: TestClient, *, name: str = "Amlodipine 5mg") -> dict:
    client.post("/api/demo/start", json={"client_id": CLIENT})
    draft = client.post(
        "/api/medications/drafts",
        params=_params(),
        json={
            "medication_name": name,
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_kind": "daily",
            "frequency_local_times": ["08:00"],
        },
    ).json()
    client.post(
        f"/api/medications/drafts/{draft['source_id']}/review",
        params=_params(),
        json={"field_ids": None},
    )
    session_id = client.post("/api/agent/messages", params=_params(), json={"text": "hello"}).json()["session_id"]
    challenge = client.post(
        f"/api/medications/drafts/{draft['regimen_id']}/challenge",
        params=_params(session_id=session_id),
    ).json()
    activated = client.post(
        "/api/medications/activate",
        params=_params(),
        json={
            "regimen_id": draft["regimen_id"],
            "challenge_id": challenge["challenge_id"],
            "session_id": session_id,
            "session_state": challenge["session_state"],
            "session_state_version": challenge["session_state_version"],
        },
    )
    assert activated.status_code == 200, activated.text
    return activated.json()


def _ask(client: TestClient, text: str, session_id: str | None = None) -> dict:
    payload: dict[str, object] = {"text": text}
    if session_id is not None:
        payload["session_id"] = session_id
    response = client.post("/api/agent/messages", params=_params(), json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_http_status_query_with_no_report_is_not_a_missed_dose(client: TestClient, clock: FixedClock) -> None:
    _activate_daily(client)
    clock.advance(hours=10)

    body = _ask(client, "Have I taken Amlodipine today?")

    assert body["intent"] == "dose_status_query"
    assert body["mode"] == "deterministic_degraded"
    assert "no confirmed dose record" in body["message"].lower()
    traces = body["tool_traces"]
    assert traces[-1]["tool_name"] == "get_dose_status"
    # The previously observed wrong answer must be gone.
    assert "active medication" not in body["message"]


def test_http_status_query_reports_a_recorded_taken_dose(client: TestClient, clock: FixedClock) -> None:
    activated = _activate_daily(client)
    clock.advance(hours=10)
    regimen_id = activated["regimen_id"]

    due = client.get("/api/doses/due", params=_params(regimen_id=regimen_id)).json()
    assert due["occurrence_id"] is not None, "a dose must be due after the clock advances"
    report = client.post(
        f"/api/doses/{due['occurrence_id']}/report",
        params=_params(),
        json={
            "regimen_id": regimen_id,
            "intake_status": "taken",
            "idempotency_key": "http-taken-1",
        },
    )
    assert report.status_code == 200, report.text

    body = _ask(client, "Have I taken Amlodipine today?")
    assert body["intent"] == "dose_status_query"
    assert "reported taking" in body["message"].lower()
    assert "does not prove" in body["message"]


def test_http_status_query_reports_unsure_verbatim(client: TestClient, clock: FixedClock) -> None:
    activated = _activate_daily(client)
    clock.advance(hours=10)
    regimen_id = activated["regimen_id"]
    due = client.get("/api/doses/due", params=_params(regimen_id=regimen_id)).json()

    client.post(
        f"/api/doses/{due['occurrence_id']}/report",
        params=_params(),
        json={"regimen_id": regimen_id, "intake_status": "unsure", "idempotency_key": "http-unsure-1"},
    )
    body = _ask(client, "Have I taken Amlodipine today?")
    assert "unsure" in body["message"].lower()
    assert "missed" not in body["message"].lower()


def test_http_unknown_medication_question_is_honest(client: TestClient) -> None:
    _activate_daily(client)
    body = _ask(client, "Have I taken Metformin today?")
    assert body["intent"] == "dose_status_query"
    assert "Metformin" in body["message"]
    assert "could not find" in body["message"].lower()


def test_http_unrelated_question_gets_a_capability_boundary(client: TestClient, clock: FixedClock) -> None:
    activated = _activate_daily(client)
    clock.advance(hours=10)
    session_id = _ask(client, "hello")["session_id"]

    # Record something first so the session has a "previous intent" to leak.
    regimen_id = activated["regimen_id"]
    client.post(
        "/api/agent/messages",
        params=_params(),
        json={
            "session_id": session_id,
            "text": "I took my dose",
            "slots": {"regimen_id": regimen_id, "intake_status": "taken", "idempotency_key": "http-leak-1"},
        },
    )

    body = _ask(client, "What is the capital of France?", session_id=session_id)
    assert body["intent"] == "clarification"
    assert "I can only help with" in body["message"]
    assert "France" not in body["message"]
    assert body["message"].startswith("[degraded: deterministic rule routing, not a live LLM]")


def test_http_status_query_is_isolated_between_clients(client: TestClient) -> None:
    _activate_daily(client)
    other = client.post(
        "/api/agent/messages",
        params={"client_id": "different-tab"},
        json={"text": "Have I taken Amlodipine today?"},
    )
    assert other.status_code == 200, other.text
    body = other.json()
    # A different evaluator identity has its own records and none of ours.
    assert "could not find" in body["message"].lower()


def test_http_dose_history_is_not_empty_for_a_freshly_activated_regimen(client: TestClient) -> None:
    """Regressions: history used to render as [] right after activation."""
    activated = _activate_daily(client)
    history = client.get(
        "/api/me/dose-history",
        params=_params(regimen_id=activated["regimen_id"], days=3),
    ).json()
    assert history["item_count"] > 0, "an activated regimen must have a visible schedule"
    assert all(entry["reported"] is False for entry in history["entries"])


def test_http_twice_daily_schedule_shows_two_slots_per_day(client: TestClient) -> None:
    """A twice-daily medication must produce two distinct slots per local day."""
    client.post("/api/demo/start", json={"client_id": CLIENT})
    draft = client.post(
        "/api/medications/drafts",
        params=_params(),
        json={
            "medication_name": "Amlodipine 5mg",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_kind": "daily",
            "frequency_local_times": ["08:00", "20:00"],
        },
    ).json()
    client.post(
        f"/api/medications/drafts/{draft['source_id']}/review",
        params=_params(),
        json={"field_ids": None},
    )
    session_id = client.post("/api/agent/messages", params=_params(), json={"text": "hello"}).json()["session_id"]
    challenge = client.post(
        f"/api/medications/drafts/{draft['regimen_id']}/challenge",
        params=_params(session_id=session_id),
    ).json()
    # The confirmation summary the patient sees must list BOTH times.
    assert challenge["summary"]["frequency"]["local_times"] == ["08:00", "20:00"]
    client.post(
        "/api/medications/activate",
        params=_params(),
        json={
            "regimen_id": draft["regimen_id"],
            "challenge_id": challenge["challenge_id"],
            "session_id": session_id,
            "session_state": challenge["session_state"],
            "session_state_version": challenge["session_state_version"],
        },
    )
    history = client.get(
        "/api/me/dose-history",
        params=_params(regimen_id=draft["regimen_id"], days=1),
    ).json()
    assert history["item_count"] == 2, "one local day of a twice-daily medicine is two doses"


def test_http_question_after_activation_does_not_leak_an_intent(client: TestClient, clock: FixedClock) -> None:
    """A free-text question after a confirmed activation must not reuse tools."""
    _activate_daily(client)
    clock.advance(hours=10)
    session_id = client.post("/api/agent/messages", params=_params(), json={"text": "hello"}).json()["session_id"]

    body = client.post(
        "/api/agent/messages",
        params=_params(),
        json={"session_id": session_id, "text": "What is the capital of France?"},
    ).json()
    assert body["intent"] == "clarification"
    assert body["tool_traces"] == []
