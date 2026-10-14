"""HTTP integration: a regimen may have several daily dose times.

Confirms the multi-time schedule works over the real HTTP surface, not just in
the domain layer: the draft accepts a list of times, activation persists one
rule per time, and each slot materialises as its own reported dose.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.transport.app_factory import create_app  # noqa: E402
from app.transport.container import build_container  # noqa: E402

FIXED_NOW = datetime(2026, 10, 12, 23, 0, tzinfo=UTC)  # 2026-10-13 07:00 Singapore
CLIENT = "multi-time-tab"


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


def _start(client: TestClient) -> dict:
    return client.post("/api/demo/start", json={"client_id": CLIENT}).json()


def _activate_twice_daily(client: TestClient, session_id: str, times: list[str]) -> dict:
    draft = client.post(
        "/api/medications/drafts",
        params=_params(),
        json={
            "medication_name": "Amlodipine",
            "dose_amount": 5,
            "dose_unit": "mg",
            "frequency_kind": "daily",
            "frequency_local_times": times,
        },
    ).json()
    assert draft["state"] == "draft", draft

    review = client.post(
        f"/api/medications/drafts/{draft['source_id']}/review",
        params=_params(),
        json={"field_ids": None},
    )
    assert review.status_code == 200, review.text

    challenge = client.post(
        f"/api/medications/drafts/{draft['regimen_id']}/challenge",
        params=_params(session_id=session_id),
    ).json()
    draft["challenge_summary"] = challenge.get("summary")

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
    return draft


def _report(
    client: TestClient,
    *,
    regimen_id: str,
    occurrence_id: str,
    intake_status: str,
    idempotency_key: str,
):
    """Record a self report through the two-phase confirmation flow.

    The database refuses a dose event that does not cite a confirmed,
    unconsumed ``record_self_report`` challenge, so the request issues one and
    submits it exactly as the real client does.
    """
    challenge = client.post(
        f"/api/doses/{occurrence_id}/report/challenge",
        params=_params(),
        json={
            "regimen_id": regimen_id,
            "intake_status": intake_status,
            "idempotency_key": idempotency_key,
        },
    )
    assert challenge.status_code == 200, challenge.text
    return client.post(
        f"/api/doses/{occurrence_id}/report",
        params=_params(),
        json={
            "regimen_id": regimen_id,
            "intake_status": intake_status,
            "idempotency_key": idempotency_key,
            "challenge_id": challenge.json()["challenge_id"],
        },
    )


def test_two_times_survive_the_round_trip(client: TestClient) -> None:
    session = _start(client)
    draft = _activate_twice_daily(client, session["session_id"], ["08:00", "20:00"])

    # The confirmation summary the patient approves must show both times.
    summary = draft["challenge_summary"]
    assert summary is not None
    assert summary["frequency"]["local_times"] == ["08:00", "20:00"]

    medications = client.get("/api/me/medications", params=_params()).json()
    assert medications["item_count"] == 1


def test_both_slots_become_due_across_the_day(client: TestClient, clock: FixedClock) -> None:
    session = _start(client)
    draft = _activate_twice_daily(client, session["session_id"], ["08:00", "20:00"])
    regimen_id = draft["regimen_id"]

    # 07:00 Singapore: nothing is due yet today.
    early = client.get("/api/doses/due", params=_params(regimen_id=regimen_id)).json()
    assert early["occurrence_id"] is None

    clock.advance(hours=10)  # 17:00 Singapore: the 08:00 dose is due
    morning = client.get("/api/doses/due", params=_params(regimen_id=regimen_id)).json()
    assert morning["occurrence_id"] is not None

    report = _report(
        client,
        regimen_id=regimen_id,
        occurrence_id=morning["occurrence_id"],
        intake_status="Taken",
        idempotency_key="morning-slot",
    )
    assert report.status_code == 200, report.text

    clock.advance(hours=4)  # 21:00 Singapore: the 20:00 dose is now due
    evening = client.get("/api/doses/due", params=_params(regimen_id=regimen_id)).json()

    assert evening["occurrence_id"] is not None
    assert evening["occurrence_id"] != morning["occurrence_id"]
    assert evening["visual_status"] == "not_checked"
    assert evening["ingestion_proven"] is False


def test_history_shows_both_slots_with_distinct_outcomes(
    client: TestClient, clock: FixedClock
) -> None:
    session = _start(client)
    draft = _activate_twice_daily(client, session["session_id"], ["08:00", "20:00"])
    regimen_id = draft["regimen_id"]
    clock.advance(hours=10)

    morning = client.get("/api/doses/due", params=_params(regimen_id=regimen_id)).json()
    _report(
        client,
        regimen_id=regimen_id,
        occurrence_id=morning["occurrence_id"],
        intake_status="Taken",
        idempotency_key="k-m",
    )

    history = client.get(
        "/api/me/dose-history", params=_params(regimen_id=regimen_id)
    ).json()

    reported = [entry for entry in history["entries"] if entry["reported"]]
    unreported = [entry for entry in history["entries"] if not entry["reported"]]
    assert len(reported) == 1
    assert reported[0]["intake_status"] == "reported_taken"
    # The later slot exists but is unreported — which is NOT a missed dose.
    assert len(unreported) >= 1
    assert "not_reported is NOT the same as missed" in history["note"]


def test_single_time_still_works_over_http(client: TestClient, clock: FixedClock) -> None:
    session = _start(client)
    draft = _activate_twice_daily(client, session["session_id"], ["08:00"])
    clock.advance(hours=10)

    due = client.get(
        "/api/doses/due", params=_params(regimen_id=draft["regimen_id"])
    ).json()
    assert due["occurrence_id"] is not None
    assert due["medication_display_name"] == "Amlodipine"


def test_empty_time_list_is_rejected(client: TestClient) -> None:
    _start(client)
    response = client.post(
        "/api/medications/drafts",
        params=_params(),
        json={
            "medication_name": "Amlodipine",
            "dose_amount": 5,
            "dose_unit": "mg",
            "frequency_kind": "daily",
            "frequency_local_times": [],
        },
    )
    # A daily schedule without any time is incomplete, not silently accepted.
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_INPUT"


def test_duplicate_times_do_not_create_duplicate_doses(
    client: TestClient, clock: FixedClock
) -> None:
    session = _start(client)
    draft = _activate_twice_daily(client, session["session_id"], ["08:00", "08:00"])
    clock.advance(hours=10)

    due = client.get(
        "/api/doses/due", params=_params(regimen_id=draft["regimen_id"])
    ).json()
    history = client.get(
        "/api/me/dose-history", params=_params(regimen_id=draft["regimen_id"], days=2)
    ).json()

    assert due["occurrence_id"] is not None
    # A repeated identical time must not produce two doses at the same instant.
    due_ats = [entry["due_at"] for entry in history["entries"]]
    assert len(due_ats) == len(set(due_ats))


def test_three_times_all_appear_in_history(client: TestClient, clock: FixedClock) -> None:
    session = _start(client)
    draft = _activate_twice_daily(client, session["session_id"], ["08:00", "13:00", "20:00"])
    # Materialise the schedule the same way the Today screen does.
    clock.advance(hours=23)  # next day 06:00 Singapore: all three slots have passed
    client.get("/api/doses/due", params=_params(regimen_id=draft["regimen_id"]))

    history = client.get(
        "/api/me/dose-history", params=_params(regimen_id=draft["regimen_id"], days=3)
    ).json()

    local_times = {
        datetime.fromisoformat(entry["due_at"]).astimezone(ZoneInfo("Asia/Singapore")).strftime("%H:%M")
        for entry in history["entries"]
        if entry["due_at"]
    }
    assert {"08:00", "13:00", "20:00"}.issubset(local_times)


def test_multi_time_regimen_isolation_between_clients(client: TestClient) -> None:
    session = _start(client)
    _activate_twice_daily(client, session["session_id"], ["08:00", "20:00"])

    other = client.get(
        "/api/me/medications", params={"client_id": "some-other-tab"}
    ).json()

    assert other["item_count"] == 0
