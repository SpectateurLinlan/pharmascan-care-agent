"""Transport-layer tests over the real FastAPI app.

** SIMULATED **
Persistence is the in-memory fake (B02: no PostgreSQL/Docker available). These
are real HTTP-level integration tests — the ASGI app genuinely routes, the
handlers genuinely execute, the error mapping genuinely applies — but the
database is not real and no claim is made that it is.
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
CLIENT = "tab-under-test"


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
    app = create_app(container)
    return TestClient(app, raise_server_exceptions=False)


def _params(**extra: object) -> dict[str, object]:
    return {"client_id": CLIENT, **extra}


def _start(client: TestClient) -> dict:
    response = client.post("/api/demo/start", json={"client_id": CLIENT})
    assert response.status_code == 200
    return response.json()


def _daily_draft(client: TestClient, **overrides: object) -> dict:
    payload = {
        "medication_name": "Amlodipine",
        "dose_amount": 5,
        "dose_unit": "mg",
        "frequency_kind": "daily",
        "frequency_local_times": ["08:00"],
    }
    payload.update(overrides)
    response = client.post(
        "/api/medications/drafts", params=_params(), json=payload
    )
    assert response.status_code == 200, response.text
    return response.json()


def _activate(client: TestClient, draft: dict, session_id: str) -> dict:
    review = client.post(
        f"/api/medications/drafts/{draft['source_id']}/review",
        params=_params(),
        json={"field_ids": None},
    )
    assert review.status_code == 200, review.text

    challenge = client.post(
        f"/api/medications/drafts/{draft['regimen_id']}/challenge",
        params=_params(session_id=session_id),
    )
    assert challenge.status_code == 200, challenge.text
    challenge_body = challenge.json()

    activated = client.post(
        "/api/medications/activate",
        params=_params(),
        json={
            "regimen_id": draft["regimen_id"],
            "challenge_id": challenge_body["challenge_id"],
            "session_id": session_id,
            "session_state": challenge_body["session_state"],
            "session_state_version": challenge_body["session_state_version"],
        },
    )
    return activated


# --- health & demo ----------------------------------------------------------


def test_health_reports_simulated_dependencies_honestly(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "simulated_in_memory"
    assert body["llm"] == "unavailable_deterministic_degraded"
    assert body["stage2_vision"] == "simulated"


def test_demo_start_is_idempotent_per_client_id(client: TestClient) -> None:
    first = _start(client)
    second = _start(client)
    assert first["patient_id"] == second["patient_id"]
    assert first["demo_only"] is True


def test_demo_start_isolates_different_clients(client: TestClient) -> None:
    a = client.post("/api/demo/start", json={"client_id": "tab-a"}).json()
    b = client.post("/api/demo/start", json={"client_id": "tab-b"}).json()
    assert a["patient_id"] != b["patient_id"]


def test_demo_start_rejects_empty_client_id(client: TestClient) -> None:
    response = client.post("/api/demo/start", json={"client_id": ""})
    assert response.status_code == 422


# --- draft lifecycle --------------------------------------------------------


def test_empty_medication_list_for_new_patient(client: TestClient) -> None:
    _start(client)
    body = client.get("/api/me/medications", params=_params()).json()
    assert body["item_count"] == 0
    assert body["medications"] == []


def test_complete_draft_is_created_but_not_active(client: TestClient) -> None:
    _start(client)
    draft = _daily_draft(client)
    assert draft["state"] == "draft"
    assert draft["missing_instructions"] == []

    listing = client.get("/api/me/medications", params=_params()).json()
    # A draft is never an active medication.
    assert listing["item_count"] == 0


def test_incomplete_draft_stays_pending_clarification(client: TestClient) -> None:
    _start(client)
    draft = _daily_draft(
        client,
        medication_name="Metformin",
        dose_amount=None,
        dose_unit=None,
        frequency_kind=None,
        frequency_local_times=[],
    )
    assert draft["state"] == "pending_clarification"
    assert "dose_amount" in draft["missing_instructions"]
    assert "dose_unit" in draft["missing_instructions"]


def test_draft_rejects_non_positive_dose(client: TestClient) -> None:
    _start(client)
    response = client.post(
        "/api/medications/drafts",
        params=_params(),
        json={"medication_name": "Amlodipine", "dose_amount": 0, "dose_unit": "mg"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_INPUT"


def test_activation_requires_explicit_confirmation(client: TestClient) -> None:
    """A reviewed draft still cannot activate without a consumed challenge."""
    started = _start(client)
    draft = _daily_draft(client)
    client.post(
        f"/api/medications/drafts/{draft['source_id']}/review",
        params=_params(),
        json={"field_ids": None},
    )
    response = client.post(
        "/api/medications/activate",
        params=_params(),
        json={
            "regimen_id": draft["regimen_id"],
            "challenge_id": str(UUID(int=999)),
            "session_id": started["session_id"],
            "session_state": "awaiting_confirmation",
            "session_state_version": 2,
        },
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_activation_before_review_is_refused(client: TestClient) -> None:
    started = _start(client)
    draft = _daily_draft(client)
    challenge = client.post(
        f"/api/medications/drafts/{draft['regimen_id']}/challenge",
        params=_params(session_id=started["session_id"]),
    ).json()
    response = client.post(
        "/api/medications/activate",
        params=_params(),
        json={
            "regimen_id": draft["regimen_id"],
            "challenge_id": challenge["challenge_id"],
            "session_id": started["session_id"],
            "session_state": challenge["session_state"],
            "session_state_version": challenge["session_state_version"],
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "SOURCE_UNREVIEWED"
    assert response.json()["rule_id"] == "SOURCE_REVIEW_REQUIRED"


def test_stale_session_version_cannot_activate(client: TestClient) -> None:
    started = _start(client)
    draft = _daily_draft(client)
    client.post(
        f"/api/medications/drafts/{draft['source_id']}/review",
        params=_params(),
        json={"field_ids": None},
    )
    challenge = client.post(
        f"/api/medications/drafts/{draft['regimen_id']}/challenge",
        params=_params(session_id=started["session_id"]),
    ).json()
    response = client.post(
        "/api/medications/activate",
        params=_params(),
        json={
            "regimen_id": draft["regimen_id"],
            "challenge_id": challenge["challenge_id"],
            "session_id": started["session_id"],
            "session_state": challenge["session_state"],
            "session_state_version": challenge["session_state_version"] - 1,
        },
    )
    assert response.status_code == 409
    # A version the server never issued is a stale-version refusal: the tab is
    # confirming a summary that no longer matches the session.
    assert response.json()["code"] == "STALE_VERSION"
    assert response.json()["rule_id"] == "CURRENT_VERSION_REQUIRED"


def test_full_activation_flow_makes_medication_active(client: TestClient) -> None:
    started = _start(client)
    draft = _daily_draft(client)
    activated = _activate(client, draft, started["session_id"])
    assert activated.status_code == 200, activated.text
    assert activated.json()["state"] == "active"

    listing = client.get("/api/me/medications", params=_params()).json()
    assert listing["item_count"] == 1
    medication = listing["medications"][0]
    assert medication["display_name"] == "Amlodipine"
    assert medication["is_prn"] is False
    # Identity is only user_reviewed, never claimed as professionally verified.
    assert medication["identity_status"] == "user_reviewed_document"


def test_challenge_summary_carries_patient_timezone(client: TestClient) -> None:
    started = _start(client)
    draft = _daily_draft(client)
    client.post(
        f"/api/medications/drafts/{draft['source_id']}/review",
        params=_params(),
        json={"field_ids": None},
    )
    body = client.post(
        f"/api/medications/drafts/{draft['regimen_id']}/challenge",
        params=_params(session_id=started["session_id"]),
    ).json()
    assert body["summary"]["local_timezone"] == "Asia/Singapore"
    assert body["summary"]["medication_name"] == "Amlodipine"
    assert body["summary"]["dose_amount"] == 5
    assert body["session_state"] == "awaiting_confirmation"


def test_challenge_for_unknown_regimen_is_404(client: TestClient) -> None:
    started = _start(client)
    response = client.post(
        f"/api/medications/drafts/{UUID(int=12345)}/challenge",
        params=_params(session_id=started["session_id"]),
    )
    assert response.status_code == 404


# --- dosing -----------------------------------------------------------------


def test_due_dose_then_self_report_then_history(client: TestClient, clock: FixedClock) -> None:
    started = _start(client)
    draft = _daily_draft(client)
    assert _activate(client, draft, started["session_id"]).status_code == 200
    regimen_id = draft["regimen_id"]

    # 07:00 SG: today's 08:00 dose is not due yet.
    before = client.get(
        "/api/doses/due", params=_params(regimen_id=regimen_id)
    ).json()
    assert before["occurrence_id"] is None

    clock.advance(hours=10)  # 17:00 SG: the 08:00 dose is now due
    due = client.get("/api/doses/due", params=_params(regimen_id=regimen_id)).json()
    assert due["occurrence_id"] is not None
    assert due["medication_display_name"] == "Amlodipine"
    assert due["visual_status"] == "not_checked"
    assert due["ingestion_proven"] is False

    report = client.post(
        f"/api/doses/{due['occurrence_id']}/report",
        params=_params(),
        json={
            "regimen_id": regimen_id,
            "intake_status": "Taken",
            "idempotency_key": "turn-1",
        },
    )
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["intake_status"] == "reported_taken"
    assert body["visual_status"] == "not_checked"
    assert body["ingestion_proven"] is False
    assert body["already_recorded"] is False

    history = client.get(
        "/api/me/dose-history", params=_params(regimen_id=regimen_id)
    ).json()
    reported = [e for e in history["entries"] if e["reported"]]
    assert len(reported) == 1
    assert reported[0]["intake_status"] == "reported_taken"


def test_self_report_is_idempotent(client: TestClient, clock: FixedClock) -> None:
    started = _start(client)
    draft = _daily_draft(client)
    _activate(client, draft, started["session_id"])
    regimen_id = draft["regimen_id"]
    clock.advance(hours=10)
    due = client.get("/api/doses/due", params=_params(regimen_id=regimen_id)).json()

    payload = {
        "regimen_id": regimen_id,
        "intake_status": "Taken",
        "idempotency_key": "same-key",
    }
    first = client.post(
        f"/api/doses/{due['occurrence_id']}/report", params=_params(), json=payload
    ).json()
    second = client.post(
        f"/api/doses/{due['occurrence_id']}/report", params=_params(), json=payload
    ).json()

    assert first["already_recorded"] is False
    assert second["already_recorded"] is True
    assert second["event_id"] == first["event_id"]


def test_unreported_dose_is_not_counted_as_missed(
    client: TestClient, clock: FixedClock
) -> None:
    started = _start(client)
    draft = _daily_draft(client)
    _activate(client, draft, started["session_id"])
    regimen_id = draft["regimen_id"]
    clock.advance(hours=10)

    history = client.get(
        "/api/me/dose-history", params=_params(regimen_id=regimen_id)
    ).json()
    assert "not_reported is NOT the same as missed" in history["note"]
    assert all(entry["intake_status"] is None for entry in history["entries"])


def test_invalid_patient_choice_is_rejected_not_defaulted(
    client: TestClient, clock: FixedClock
) -> None:
    started = _start(client)
    draft = _daily_draft(client)
    _activate(client, draft, started["session_id"])
    regimen_id = draft["regimen_id"]
    clock.advance(hours=10)
    due = client.get("/api/doses/due", params=_params(regimen_id=regimen_id)).json()

    response = client.post(
        f"/api/doses/{due['occurrence_id']}/report",
        params=_params(),
        json={
            "regimen_id": regimen_id,
            "intake_status": "definitely-swallowed-it",
            "idempotency_key": "k",
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_INPUT"


def test_patient_facing_choice_labels_are_accepted(
    client: TestClient, clock: FixedClock
) -> None:
    started = _start(client)
    draft = _daily_draft(client)
    _activate(client, draft, started["session_id"])
    regimen_id = draft["regimen_id"]
    clock.advance(hours=10)
    due = client.get("/api/doses/due", params=_params(regimen_id=regimen_id)).json()

    response = client.post(
        f"/api/doses/{due['occurrence_id']}/report",
        params=_params(),
        json={
            "regimen_id": regimen_id,
            "intake_status": "Not now",
            "idempotency_key": "k2",
        },
    )
    assert response.status_code == 200
    assert response.json()["intake_status"] == "reported_not_taken"


def test_prn_regimen_has_no_scheduled_due_dose(client: TestClient) -> None:
    started = _start(client)
    draft = _daily_draft(
        client,
        medication_name="Paracetamol",
        is_prn=True,
        frequency_kind=None,
        frequency_local_times=[],
        food_instruction="as needed for pain",
    )
    assert _activate(client, draft, started["session_id"]).status_code == 200

    due = client.get(
        "/api/doses/due", params=_params(regimen_id=draft["regimen_id"])
    ).json()
    assert due["is_prn"] is True
    assert due["occurrence_id"] is None


def test_due_dose_for_unknown_regimen_is_404(client: TestClient) -> None:
    _start(client)
    response = client.get(
        "/api/doses/due", params=_params(regimen_id=UUID(int=777))
    )
    assert response.status_code == 404


# --- agent ------------------------------------------------------------------


def test_agent_reply_is_labelled_degraded(client: TestClient) -> None:
    started = _start(client)
    response = client.post(
        "/api/agent/messages",
        params=_params(),
        json={
            "text": "I want to add my blood pressure tablet",
            "session_id": started["session_id"],
            "client_turn_id": "t1",
            "slots": {
                "medication_name": "Amlodipine",
                "dose_amount": 5,
                "dose_unit": "mg",
                "frequency_kind": "daily",
                "frequency_local_times": ["08:00"],
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # The mode must be surfaced so the UI cannot claim a live LLM.
    assert body["mode"] == "deterministic_degraded"
    assert body["message"].startswith("[degraded:")
    assert body["intent"] == "medication_enrollment"
    assert body["tool_traces"][0]["tool_name"] == "enroll_medication_draft"


def test_agent_traces_are_redacted(client: TestClient) -> None:
    started = _start(client)
    response = client.post(
        "/api/agent/messages",
        params=_params(),
        json={
            "text": "add medication",
            "session_id": started["session_id"],
            "client_turn_id": "t2",
            "slots": {
                "medication_name": "Amlodipine",
                "dose_amount": 5,
                "dose_unit": "mg",
                "frequency_kind": "daily",
                "frequency_local_times": ["08:00"],
            },
        },
    )
    traces = response.json()["tool_traces"]
    for trace in traces:
        # Free-text patient input must never appear in a trace payload.
        assert "Amlodipine" not in str(trace["payload"])
        assert "5" not in str(trace["payload"].get("medication_name", ""))


def test_agent_session_id_is_echoed_back(client: TestClient) -> None:
    started = _start(client)
    response = client.post(
        "/api/agent/messages",
        params=_params(),
        json={"text": "hello", "session_id": started["session_id"], "client_turn_id": "t3"},
    )
    assert response.status_code == 200
    assert response.json()["session_id"] == started["session_id"]


def test_agent_creates_session_when_none_supplied(client: TestClient) -> None:
    _start(client)
    response = client.post(
        "/api/agent/messages",
        params=_params(),
        json={"text": "what should I take", "client_turn_id": "t4"},
    )
    assert response.status_code == 200
    assert response.json()["session_id"]


def test_agent_is_bounded_and_budgeted(client: TestClient, clock: FixedClock) -> None:
    """One self-report turn performs a bounded, deterministic tool sequence."""
    started = _start(client)
    draft = _daily_draft(client)
    _activate(client, draft, started["session_id"])
    clock.advance(hours=10)

    response = client.post(
        "/api/agent/messages",
        params=_params(),
        json={
            "text": "I took it",
            "session_id": started["session_id"],
            "client_turn_id": "t5",
            "slots": {
                "regimen_id": draft["regimen_id"],
                "intake_status": "Taken",
                "idempotency_key": "t5",
            },
        },
    )
    assert response.status_code == 200
    tools = [t["tool_name"] for t in response.json()["tool_traces"]]
    # Never exceeds the 4-step budget, and follows the documented order.
    assert len(tools) <= 4
    assert tools[-1] == "record_self_report"


def test_unknown_tool_is_not_reachable_over_http(client: TestClient) -> None:
    """There is no generic 'run any tool' endpoint."""
    _start(client)
    response = client.post(
        "/api/agent/messages",
        params=_params(),
        json={
            "text": "do it",
            "client_turn_id": "t6",
            "slots": {"tool_name": "drop_all_tables"},
        },
    )
    assert response.status_code == 200
    tools = [t["tool_name"] for t in response.json()["tool_traces"]]
    assert "drop_all_tables" not in tools


# --- cross-cutting ----------------------------------------------------------


def test_missing_client_id_is_rejected(client: TestClient) -> None:
    assert client.get("/api/me/medications").status_code == 422


def test_openapi_schema_is_generated(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "PharmaScan Care Agent API"
    assert "/api/medications/drafts" in schema["paths"]
    assert "/api/agent/messages" in schema["paths"]
