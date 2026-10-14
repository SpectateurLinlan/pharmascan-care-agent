"""Self-report confirmation lifecycle (Session 3D, resolves B14).

** SIMULATED ** persistence, real policy, real service, real ASGI app.

The database requires every ``dose_events`` row to cite a confirmed, unconsumed
``record_self_report`` challenge (``confirmation_challenge_id NOT NULL`` plus
``core_guard_dose_event`` -> ``core_consume_confirmation``). These tests lock
the application-side lifecycle that completes it, and — just as importantly —
lock the *refusals*: a report that has no challenge, an unconfirmed challenge,
an expired one, an already-consumed one, another patient's challenge, and a
duplicate confirmation must all be refused rather than accommodated.

The equivalent assertions against the real database live in
``scripts/db_integration.py``; these run without a database so the contract
cannot regress silently.
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
CLIENT = "tab-b14"
OTHER_CLIENT = "tab-b14-other"


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


def _fresh_client(moment: datetime = FIXED_NOW) -> tuple[TestClient, FixedClock]:
    """An isolated app + clock, so two activations cannot disturb each other."""
    fresh_clock = FixedClock(moment)
    container = build_container(clock=fresh_clock, ids=CountingIdGenerator())
    return TestClient(create_app(container), raise_server_exceptions=False), fresh_clock


def _p(client_id: str = CLIENT, **extra: object) -> dict[str, object]:
    return {"client_id": client_id, **extra}


def _activate_due_regimen(client: TestClient, clock: FixedClock, client_id: str = CLIENT) -> tuple[str, str]:
    """Activate a daily regimen and advance so today's dose is due."""
    client.post("/api/demo/start", json={"client_id": client_id})
    draft = client.post(
        "/api/medications/drafts",
        params=_p(client_id),
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
        params=_p(client_id),
        json={"field_ids": None},
    )
    session_id = client.post("/api/agent/messages", params=_p(client_id), json={"text": "hello"}).json()["session_id"]
    challenge = client.post(
        f"/api/medications/drafts/{draft['regimen_id']}/challenge",
        params=_p(client_id, session_id=session_id),
    ).json()
    activated = client.post(
        "/api/medications/activate",
        params=_p(client_id),
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
    due = client.get("/api/doses/due", params=_p(client_id, regimen_id=draft["regimen_id"])).json()
    assert due["occurrence_id"] is not None
    return draft["regimen_id"], due["occurrence_id"]


def _request_challenge(
    client: TestClient,
    *,
    regimen_id: str,
    occurrence_id: str,
    intake_status: str,
    idempotency_key: str,
    client_id: str = CLIENT,
):
    return client.post(
        f"/api/doses/{occurrence_id}/report/challenge",
        params=_p(client_id),
        json={
            "regimen_id": regimen_id,
            "intake_status": intake_status,
            "idempotency_key": idempotency_key,
        },
    )


def _submit(
    client: TestClient,
    *,
    regimen_id: str,
    occurrence_id: str,
    intake_status: str,
    idempotency_key: str,
    challenge_id: str,
    client_id: str = CLIENT,
):
    return client.post(
        f"/api/doses/{occurrence_id}/report",
        params=_p(client_id),
        json={
            "regimen_id": regimen_id,
            "intake_status": intake_status,
            "idempotency_key": idempotency_key,
            "challenge_id": challenge_id,
        },
    )


# --- the happy path ---------------------------------------------------------


def test_challenge_then_confirm_records_the_report(client: TestClient, clock: FixedClock) -> None:
    regimen_id, occurrence_id = _activate_due_regimen(client, clock)

    challenge = _request_challenge(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-1",
    )
    assert challenge.status_code == 200, challenge.text
    body = challenge.json()
    assert body["challenge_id"] is not None
    assert body["already_recorded"] is False
    # The summary must state what is being recorded without claiming ingestion.
    assert body["summary"]["intake_status"] == "reported_taken"
    assert body["summary"]["ingestion_proven"] is False
    assert body["summary"]["visual_status"] == "not_checked"
    assert "does not prove" in body["summary"]["safety_notice"]
    assert body["summary"]["medication_display_name"] == "Amlodipine 5mg"
    assert body["summary"]["occurrence_due_at"] is not None

    recorded = _submit(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-1",
        challenge_id=body["challenge_id"],
    )
    assert recorded.status_code == 200, recorded.text
    result = recorded.json()
    assert result["already_recorded"] is False
    assert result["event_id"] is not None
    assert result["intake_status"] == "reported_taken"
    assert result["visual_status"] == "not_checked"
    assert result["ingestion_proven"] is False


def test_challenge_alone_writes_nothing(client: TestClient, clock: FixedClock) -> None:
    """Phase 1 must be side-effect free apart from the session state move."""
    regimen_id, occurrence_id = _activate_due_regimen(client, clock)
    _request_challenge(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-noop",
    )
    history = client.get("/api/me/dose-history", params=_p(regimen_id=regimen_id, days=2)).json()
    assert all(not entry["reported"] for entry in history["entries"])


def test_unsure_and_not_now_are_recorded_verbatim() -> None:
    for choice, expected in (("unsure", "unsure"), ("Not now", "reported_not_taken")):
        case_client, case_clock = _fresh_client()
        client_id = f"{CLIENT}-{expected}"
        regimen_id, occurrence_id = _activate_due_regimen(case_client, case_clock, client_id=client_id)
        body = _request_challenge(
            case_client,
            regimen_id=regimen_id,
            occurrence_id=occurrence_id,
            intake_status=choice,
            idempotency_key=f"b14-{expected}",
            client_id=client_id,
        ).json()
        recorded = _submit(
            case_client,
            regimen_id=regimen_id,
            occurrence_id=occurrence_id,
            intake_status=choice,
            idempotency_key=f"b14-{expected}",
            challenge_id=body["challenge_id"],
            client_id=client_id,
        ).json()
        assert recorded["intake_status"] == expected


# --- idempotency ------------------------------------------------------------


def test_replaying_the_same_key_returns_the_existing_event(client: TestClient, clock: FixedClock) -> None:
    regimen_id, occurrence_id = _activate_due_regimen(client, clock)
    challenge = _request_challenge(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-idem",
    ).json()
    first = _submit(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-idem",
        challenge_id=challenge["challenge_id"],
    ).json()

    # A replay re-requests the challenge (answered as already recorded) and then
    # re-submits; the second submit must return the same event, not a second one.
    replay = _request_challenge(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-idem",
    ).json()
    assert replay["already_recorded"] is True
    assert replay["challenge_id"] is None

    second = _submit(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-idem",
        challenge_id=challenge["challenge_id"],
    ).json()
    assert second["already_recorded"] is True
    assert second["event_id"] == first["event_id"]


def test_reissuing_a_challenge_for_the_same_key_reuses_it(client: TestClient, clock: FixedClock) -> None:
    """A double-tap must not attempt a second insert (UNIQUE patient_id, key)."""
    regimen_id, occurrence_id = _activate_due_regimen(client, clock)
    first = _request_challenge(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-reuse",
    ).json()
    second = _request_challenge(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-reuse",
    )
    assert second.status_code == 200, second.text
    assert second.json()["challenge_id"] == first["challenge_id"]
    assert second.json()["session_id"] == first["session_id"]
    completed = _submit(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-reuse",
        challenge_id=first["challenge_id"],
    )
    assert completed.status_code == 200


def test_wrong_purpose_challenge_is_refused(client: TestClient, clock: FixedClock) -> None:
    from app.domain.errors import ConfirmationRequiredError

    regimen_id, occurrence_id = _activate_due_regimen(client, clock)
    issued = _request_challenge(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="wrong-purpose",
    ).json()
    container = client.app.state.container
    patient = container.auth.resolve(authorization=None, client_id=CLIENT).patient_id
    challenge = container.store.challenges[(patient, UUID(issued["challenge_id"]))]
    container.store.challenges[(patient, challenge.id)] = challenge.model_copy(update={"action": "activate_regimen"})
    with pytest.raises(ConfirmationRequiredError):
        container.self_report.confirm_challenge(patient_id=patient, challenge_id=challenge.id)
    assert not container.store.events


def test_replay_with_different_intake_is_refused(client: TestClient, clock: FixedClock) -> None:
    regimen, occurrence = _activate_due_regimen(client, clock)
    challenge = _request_challenge(
        client, regimen_id=regimen, occurrence_id=occurrence, intake_status="taken", idempotency_key="binding-key"
    ).json()
    assert (
        _submit(
            client,
            regimen_id=regimen,
            occurrence_id=occurrence,
            intake_status="taken",
            idempotency_key="binding-key",
            challenge_id=challenge["challenge_id"],
        ).status_code
        == 200
    )
    changed = _submit(
        client,
        regimen_id=regimen,
        occurrence_id=occurrence,
        intake_status="unsure",
        idempotency_key="binding-key",
        challenge_id=challenge["challenge_id"],
    )
    assert changed.status_code == 409 and changed.json()["code"] == "DUPLICATE_EVENT"
    assert len(client.app.state.container.store.events) == 1


def test_stale_session_version_is_refused(client: TestClient, clock: FixedClock) -> None:
    regimen, occurrence = _activate_due_regimen(client, clock)
    challenge = _request_challenge(
        client, regimen_id=regimen, occurrence_id=occurrence, intake_status="taken", idempotency_key="stale-session"
    ).json()
    container = client.app.state.container
    patient = container.auth.resolve(authorization=None, client_id=CLIENT).patient_id
    container.orchestrator.await_confirmation(patient_id=patient, session_id=UUID(challenge["session_id"]))
    result = _submit(
        client,
        regimen_id=regimen,
        occurrence_id=occurrence,
        intake_status="taken",
        idempotency_key="stale-session",
        challenge_id=challenge["challenge_id"],
    )
    assert result.status_code == 409 and result.json()["code"] == "STALE_VERSION"
    assert not container.store.events


# --- refusals ---------------------------------------------------------------


@pytest.mark.parametrize(
    "choice,stored", [("taken", "reported_taken"), ("not_taken", "reported_not_taken"), ("unsure", "unsure")]
)
def test_prn_confirmation_has_no_occurrence_and_keeps_report_history(client: TestClient, choice: str, stored: str):
    start = client.post("/api/demo/start", json={"client_id": CLIENT}).json()
    draft = client.post(
        "/api/medications/drafts",
        params=_p(),
        json={
            "medication_name": "DEMO PRN medicine",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "is_prn": True,
            "food_instruction": "DEMO reviewed as-needed condition",
        },
    ).json()
    client.post(f"/api/medications/drafts/{draft['source_id']}/review", params=_p(), json={"field_ids": None})
    activation = client.post(
        f"/api/medications/drafts/{draft['regimen_id']}/challenge", params=_p(session_id=start["session_id"])
    ).json()
    assert (
        client.post(
            "/api/medications/activate",
            params=_p(),
            json={
                "regimen_id": draft["regimen_id"],
                "challenge_id": activation["challenge_id"],
                "session_id": start["session_id"],
                "session_state": activation["session_state"],
                "session_state_version": activation["session_state_version"],
            },
        ).status_code
        == 200
    )
    body = {"regimen_id": draft["regimen_id"], "intake_status": choice, "idempotency_key": "DEMO-prn"}
    pending = client.post("/api/prn/report/challenge", params=_p(), json=body).json()
    assert pending["occurrence_id"] is None and not client.app.state.container.store.events
    body["challenge_id"] = pending["challenge_id"]
    saved = client.post("/api/prn/report", params=_p(), json=body)
    assert saved.status_code == 200 and saved.json()["intake_status"] == stored
    assert client.post("/api/prn/report", params=_p(), json=body).json()["already_recorded"]
    history = client.get("/api/me/dose-history", params=_p(regimen_id=draft["regimen_id"])).json()
    assert history["item_count"] == 1 and history["entries"][0]["event_time"]
    assert not client.app.state.container.store.occurrences


def test_mismatched_submission_does_not_arm_confirmation(client: TestClient, clock: FixedClock):
    regimen, occurrence = _activate_due_regimen(client, clock)
    response = _request_challenge(
        client,
        regimen_id=regimen,
        occurrence_id=occurrence,
        intake_status="taken",
        idempotency_key="mismatch-before-confirm",
    ).json()
    attempted = _submit(
        client,
        regimen_id=regimen,
        occurrence_id=occurrence,
        intake_status="unsure",
        idempotency_key="mismatch-before-confirm",
        challenge_id=response["challenge_id"],
    )
    assert attempted.status_code == 409
    container = client.app.state.container
    patient = container.auth.resolve(authorization=None, client_id=CLIENT).patient_id
    challenge = container.store.challenges[(patient, UUID(response["challenge_id"]))]
    assert challenge.confirmed_at is None and challenge.consumed_at is None and not container.store.events


def test_agent_transcript_creates_summary_then_requires_explicit_confirmation(client: TestClient, clock: FixedClock):
    regimen, occurrence = _activate_due_regimen(client, clock)
    payload = {"text": "I took it.", "client_turn_id": "DEMO-voice-turn", "slots": {}}
    first = client.post("/api/agent/messages", params=_p(), json=payload)
    assert first.status_code == 200
    pending = first.json()["pending_report"]
    assert pending and first.json()["requires_confirmation"]
    assert pending["regimen_id"] == regimen and pending["occurrence_id"] == occurrence
    assert pending["summary"]["intake_status"] == "reported_taken"
    assert not client.app.state.container.store.events
    retry = client.post("/api/agent/messages", params=_p(), json=payload)
    assert retry.json()["pending_report"]["challenge_id"] == pending["challenge_id"]
    assert retry.json()["session_id"] == first.json()["session_id"]
    assert not client.app.state.container.store.events
    saved = _submit(
        client,
        regimen_id=regimen,
        occurrence_id=occurrence,
        intake_status="reported_taken",
        idempotency_key=pending["idempotency_key"],
        challenge_id=pending["challenge_id"],
    )
    assert saved.status_code == 200 and len(client.app.state.container.store.events) == 1


def test_report_without_a_challenge_is_refused(client: TestClient, clock: FixedClock) -> None:
    regimen_id, occurrence_id = _activate_due_regimen(client, clock)
    response = client.post(
        f"/api/doses/{occurrence_id}/report",
        params=_p(),
        json={
            "regimen_id": regimen_id,
            "intake_status": "taken",
            "idempotency_key": "b14-none",
        },
    )
    # challenge_id is a required field of the request contract.
    assert response.status_code == 422


def test_unknown_challenge_is_refused(client: TestClient, clock: FixedClock) -> None:
    regimen_id, occurrence_id = _activate_due_regimen(client, clock)
    response = _submit(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-unknown",
        challenge_id=str(UUID(int=987654321)),
    )
    assert response.status_code >= 400
    assert response.json()["code"] == "CONFIRMATION_REQUIRED"


def test_unconfirmed_challenge_is_refused(client: TestClient, clock: FixedClock) -> None:
    """A challenge that was issued but never confirmed must not record a dose.

    The route confirms as part of phase 2, so this is asserted at the service
    layer, where the guarantee actually lives.
    """
    regimen_id, occurrence_id = _activate_due_regimen(client, clock)
    challenge = _request_challenge(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-unconfirmed",
    ).json()
    service = client.app.state.container.self_report
    challenge_uuid = UUID(challenge["challenge_id"])
    stored = service._challenges.get(
        client.app.state.container.auth.resolve(authorization=None, client_id=CLIENT).patient_id,
        challenge_uuid,
    )
    assert stored is not None and stored.confirmed_at is None
    with pytest.raises(Exception) as excinfo:
        service.report(
            patient_id=stored.patient_id,
            payload=_payload(regimen_id, occurrence_id, "taken", "b14-unconfirmed"),
            challenge_id=challenge_uuid,
        )
    assert getattr(excinfo.value, "code", None) is not None
    assert excinfo.value.code.value == "CONFIRMATION_REQUIRED"


def test_expired_challenge_is_refused(client: TestClient, clock: FixedClock) -> None:
    regimen_id, occurrence_id = _activate_due_regimen(client, clock)
    challenge = _request_challenge(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-expired",
    ).json()

    # Past the ten-minute challenge window (the database caps it at exactly
    # that, so this cannot be extended).
    clock.advance(minutes=11)
    response = _submit(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-expired",
        challenge_id=challenge["challenge_id"],
    )
    assert response.status_code >= 400
    assert response.json()["code"] == "CONFIRMATION_EXPIRED"


def test_already_consumed_challenge_cannot_be_reused(client: TestClient, clock: FixedClock) -> None:
    regimen_id, occurrence_id = _activate_due_regimen(client, clock)
    challenge = _request_challenge(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-consumed",
    ).json()
    first = _submit(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-consumed",
        challenge_id=challenge["challenge_id"],
    )
    assert first.status_code == 200

    # A second, distinct report reusing the consumed challenge must be refused.
    second = _submit(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-consumed-2",
        challenge_id=challenge["challenge_id"],
    )
    assert second.status_code >= 400
    assert second.json()["code"] in {"CONFIRMATION_EXPIRED", "DUPLICATE_EVENT"}


def test_duplicate_confirmation_of_a_consumed_challenge_is_refused(client: TestClient, clock: FixedClock) -> None:
    regimen_id, occurrence_id = _activate_due_regimen(client, clock)
    challenge = _request_challenge(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-dup-confirm",
    ).json()
    _submit(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-dup-confirm",
        challenge_id=challenge["challenge_id"],
    )
    service = client.app.state.container.self_report
    patient_id = client.app.state.container.auth.resolve(authorization=None, client_id=CLIENT).patient_id
    with pytest.raises(Exception) as excinfo:
        service.confirm_challenge(patient_id=patient_id, challenge_id=UUID(challenge["challenge_id"]))
    assert excinfo.value.code.value == "CONFIRMATION_EXPIRED"


def test_another_patients_challenge_cannot_be_used(client: TestClient, clock: FixedClock) -> None:
    """B must not be able to complete A's report with A's challenge id."""
    regimen_a, occurrence_a = _activate_due_regimen(client, clock, client_id="patient-a")
    challenge_a = _request_challenge(
        client,
        regimen_id=regimen_a,
        occurrence_id=occurrence_a,
        intake_status="taken",
        idempotency_key="b14-cross",
        client_id="patient-a",
    ).json()

    # B is a distinct synthetic patient. B needs no schedule of its own: the
    # point is that A's regimen, occurrence and challenge are all invisible.
    client.post("/api/demo/start", json={"client_id": "patient-b"})
    response = _submit(
        client,
        regimen_id=regimen_a,
        occurrence_id=occurrence_a,
        intake_status="taken",
        idempotency_key="b14-cross",
        challenge_id=challenge_a["challenge_id"],
        client_id="patient-b",
    )
    assert response.status_code >= 400
    # B cannot even see A's regimen, so the request never reaches a write.
    assert response.json()["code"] in {"NOT_FOUND", "CONFIRMATION_REQUIRED"}

    # B's attempt neither consumed nor stole A's challenge: A can still complete
    # its own report with the very same challenge id.
    completed = _submit(
        client,
        regimen_id=regimen_a,
        occurrence_id=occurrence_a,
        intake_status="taken",
        idempotency_key="b14-cross",
        challenge_id=challenge_a["challenge_id"],
        client_id="patient-a",
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["already_recorded"] is False


def test_second_distinct_report_on_a_closed_occurrence_is_refused(client: TestClient, clock: FixedClock) -> None:
    regimen_id, occurrence_id = _activate_due_regimen(client, clock)
    challenge = _request_challenge(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-first",
    ).json()
    _submit(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-first",
        challenge_id=challenge["challenge_id"],
    )
    second = _request_challenge(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="b14-second",
    )
    assert second.status_code >= 400
    assert second.json()["code"] == "DUPLICATE_EVENT"


def test_an_out_of_charset_idempotency_key_is_refused(client: TestClient, clock: FixedClock) -> None:
    """The key must satisfy the database CHECK; rejected as INVALID_INPUT."""
    regimen_id, occurrence_id = _activate_due_regimen(client, clock)
    response = _request_challenge(
        client,
        regimen_id=regimen_id,
        occurrence_id=occurrence_id,
        intake_status="taken",
        idempotency_key="bad key with spaces!",
    )
    assert response.status_code == 422


def _payload(regimen_id: str, occurrence_id: str, intake_status: str, key: str):
    from app.contracts.dto import DoseEventInput
    from app.domain.policy import intake_status_from_patient_choice

    return DoseEventInput(
        regimen_id=UUID(regimen_id),
        occurrence_id=UUID(occurrence_id),
        intake_status=intake_status_from_patient_choice(intake_status),
        event_time=FIXED_NOW,
        idempotency_key=key,
    )
