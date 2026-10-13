"""Dose self-report UX + confirmation invariants (Session 3A item 2).

** SIMULATED ** persistence, real ASGI app and real policy.

The patient-facing acceptance criteria for the self-report flow:
- a due dose offers Taken / Not taking / Unsure;
- clicking a button is explicitly NOT proof of ingestion;
- a repeated click does not create a second event (idempotent);
- once an occurrence is reported, a second distinct report is refused;
- an unreported dose is never presented as missed.

These are already enforced by the domain policy; this file locks the HTTP
contract so a future refactor cannot quietly weaken it.
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

FIXED_NOW = datetime(2026, 10, 12, 23, 0, tzinfo=UTC)
CLIENT = "tab-selfreport"


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


def _activate_due_regimen(client: TestClient, clock: FixedClock) -> tuple[str, str]:
    """Activate a daily regimen and advance so today's dose is due."""
    client.post("/api/demo/start", json={"client_id": CLIENT})
    draft = client.post(
        "/api/medications/drafts",
        params=_params(),
        json={
            "medication_name": "Amlodipine 5mg",
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
    session_id = client.post(
        "/api/agent/messages", params=_params(), json={"text": "hello"}
    ).json()["session_id"]
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
    clock.advance(hours=10)
    due = client.get(
        "/api/doses/due", params=_params(regimen_id=draft["regimen_id"])
    ).json()
    assert due["occurrence_id"] is not None
    return draft["regimen_id"], due["occurrence_id"]


def test_taken_report_is_recorded_without_claiming_ingestion(client: TestClient, clock: FixedClock) -> None:
    regimen_id, occurrence_id = _activate_due_regimen(client, clock)
    body = client.post(
        f"/api/doses/{occurrence_id}/report",
        params=_params(),
        json={"regimen_id": regimen_id, "intake_status": "taken", "idempotency_key": "sr-1"},
    ).json()
    assert body["intake_status"] == "reported_taken"
    # The response must never assert ingestion.
    assert body["visual_status"] == "not_checked"
    assert body["already_recorded"] is False


def test_repeated_click_with_the_same_key_is_idempotent(client: TestClient, clock: FixedClock) -> None:
    regimen_id, occurrence_id = _activate_due_regimen(client, clock)
    payload = {"regimen_id": regimen_id, "intake_status": "taken", "idempotency_key": "sr-idem"}

    first = client.post(f"/api/doses/{occurrence_id}/report", params=_params(), json=payload).json()
    second = client.post(f"/api/doses/{occurrence_id}/report", params=_params(), json=payload).json()

    assert first["already_recorded"] is False
    assert second["already_recorded"] is True
    # One event only, despite two clicks.
    assert first["event_id"] == second["event_id"]


def test_a_second_distinct_report_on_the_same_occurrence_is_refused(client: TestClient, clock: FixedClock) -> None:
    regimen_id, occurrence_id = _activate_due_regimen(client, clock)
    client.post(
        f"/api/doses/{occurrence_id}/report",
        params=_params(),
        json={"regimen_id": regimen_id, "intake_status": "taken", "idempotency_key": "sr-a"},
    )
    blocked = client.post(
        f"/api/doses/{occurrence_id}/report",
        params=_params(),
        json={"regimen_id": regimen_id, "intake_status": "taken", "idempotency_key": "sr-b"},
    )
    assert blocked.status_code >= 400
    assert blocked.json()["code"] == "DUPLICATE_EVENT"


def test_unsure_report_is_accepted_and_not_converted(client: TestClient, clock: FixedClock) -> None:
    regimen_id, occurrence_id = _activate_due_regimen(client, clock)
    body = client.post(
        f"/api/doses/{occurrence_id}/report",
        params=_params(),
        json={"regimen_id": regimen_id, "intake_status": "unsure", "idempotency_key": "sr-unsure"},
    ).json()
    assert body["intake_status"] == "unsure"


def test_not_now_report_maps_to_reported_not_taken(client: TestClient, clock: FixedClock) -> None:
    regimen_id, occurrence_id = _activate_due_regimen(client, clock)
    body = client.post(
        f"/api/doses/{occurrence_id}/report",
        params=_params(),
        json={"regimen_id": regimen_id, "intake_status": "Not now", "idempotency_key": "sr-notnow"},
    ).json()
    assert body["intake_status"] == "reported_not_taken"


def test_an_unrecognised_choice_is_refused_not_defaulted(client: TestClient, clock: FixedClock) -> None:
    regimen_id, occurrence_id = _activate_due_regimen(client, clock)
    response = client.post(
        f"/api/doses/{occurrence_id}/report",
        params=_params(),
        json={"regimen_id": regimen_id, "intake_status": "probably maybe", "idempotency_key": "sr-bad"},
    )
    assert response.status_code >= 400
    assert response.json()["code"] == "INVALID_INPUT"


def test_unreported_dose_in_history_is_labelled_not_missed(client: TestClient, clock: FixedClock) -> None:
    regimen_id, _occurrence_id = _activate_due_regimen(client, clock)
    history = client.get(
        "/api/me/dose-history", params=_params(regimen_id=regimen_id, days=2)
    ).json()
    unreported = [entry for entry in history["entries"] if not entry["reported"]]
    assert unreported, "a freshly activated dose has no report"
    for entry in unreported:
        assert entry["intake_status"] is None
        assert entry["reported"] is False
