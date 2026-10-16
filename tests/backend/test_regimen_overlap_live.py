"""Opt-in025 acceptance: real Supabase/JWT, synthetic owners, no model calls.

Append-only synthetic histories are retained. No existing patient is reused or
cleaned up. Concurrent transport gates synchronize real PATCH requests, not mocks.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from app.config import Settings
from app.contracts.enums import RegimenState
from app.domain.errors import AuthenticationRequiredError, RegimenOverlapError, ValidationError
from app.infrastructure.supabase_data import SupabaseDataClient
from app.infrastructure.supabase_repos import build_supabase_repositories
from app.transport.app_factory import create_app
from app.transport.container import ApplicationContainer, build_supabase_container
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_MIGRATION025_LIVE") != "1", reason="025 synthetic Supabase writes require explicit opt-in"
)


class Clock:
    def __init__(self) -> None:
        self.moment = datetime.now(UTC) - timedelta(minutes=2)

    def now(self) -> datetime:
        return self.moment


@dataclass
class Harness:
    settings: Settings
    app: TestClient
    root: ApplicationContainer
    clock: Clock
    owners: list[UUID]
    tokens: list[str] = field(repr=False)
    clients: list[SupabaseDataClient] = field(repr=False)
    run_id: str = ""

    def headers(self, owner: int = 0) -> dict[str, str]:
        return {"Authorization": "Bearer " + self.tokens[owner]}

    def call(self, method: str, path: str, owner: int = 0, **kwargs):
        response = self.app.request(method, path, headers=self.headers(owner), **kwargs)
        assert response.status_code == 200, (
            f"Synthetic025 API failed: {method} {path.split('?')[0]} HTTP{response.status_code}"
        )
        return response.json()

    def draft(self, name: str, *, owner: int = 0, prn: bool = False, amount: int = 1):
        body = {"medication_name": name, "dose_amount": amount, "dose_unit": "tablet", "is_prn": prn}
        if prn:
            body["food_instruction"] = "DEMO-only reviewed as-needed instruction; follow reliable source"
        else:
            local_time = (datetime.now(UTC) - timedelta(minutes=1)).astimezone(ZoneInfo("Asia/Singapore"))
            body.update(frequency_kind="daily", frequency_local_times=[local_time.strftime("%H:%M")])
        result = self.call("POST", "/api/medications/drafts", owner, json=body)
        self.call("POST", f"/api/medications/drafts/{result['source_id']}/review", owner, json={"field_ids": None})
        return result

    def challenge(self, draft, owner: int = 0):
        started = self.call("POST", "/api/demo/start", owner, json={"client_id": "DEMO025-" + uuid4().hex})
        return self.call(
            "POST",
            f"/api/medications/drafts/{draft['regimen_id']}/challenge",
            owner,
            params={"session_id": started["session_id"]},
        )

    def activate(self, challenge, owner: int = 0):
        return self.call(
            "POST",
            "/api/medications/activate",
            owner,
            json={
                k: challenge[k]
                for k in ("regimen_id", "challenge_id", "session_id", "session_state", "session_state_version")
            },
        )


@pytest.fixture(scope="module")
def live025():
    settings = replace(
        Settings.from_env(),
        database_url=None,
        supabase_secret_key=None,
        persistence="supabase",
        auth_mode="supabase",
        enable_demo_seed=False,
        model_provider="deterministic",
        vision_api_base_url=None,
        enable_web_push=False,
    )
    run_id = "DEMO025-" + uuid4().hex
    owners, tokens = [], []
    with httpx.Client(timeout=15) as http:
        for label in ("A", "B"):
            response = http.post(
                settings.require_supabase_url() + "/auth/v1/signup",
                headers={"apikey": settings.require_publishable_key()},
                json={"data": {"demo_only": True, "test_session": run_id, "synthetic_owner": label}},
            )
            assert response.status_code == 200, "025 anonymous synthetic signup failed"
            payload = response.json()
            assert bool(payload.get("access_token")), "025 token absent"
            assert payload["user"]["is_anonymous"] is True, "025 expected anonymous synthetic identity"
            owners.append(UUID(payload["user"]["id"]))
            tokens.append(payload["access_token"])
    manifest = {"run_id": run_id, "synthetic_owner_ids": [str(owner) for owner in owners], "tokens_persisted": False}
    output = Path("outputs/migration025")
    output.mkdir(parents=True, exist_ok=True)
    latest = output / "test-objects.json"
    if latest.exists():
        previous = json.loads(latest.read_text(encoding="utf-8"))
        (output / f"test-objects-{previous['run_id']}.json").write_text(
            json.dumps(previous, indent=2), encoding="utf-8"
        )
    latest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    clock = Clock()
    root = build_supabase_container(settings=settings, clock=clock)
    clients = [
        SupabaseDataClient(
            base_url=settings.require_supabase_url(),
            publishable_key=settings.require_publishable_key(),
            patient_id=owner,
            access_token=token,
        )
        for owner, token in zip(owners, tokens, strict=True)
    ]
    with TestClient(create_app(container=root), raise_server_exceptions=False) as app:
        harness = Harness(settings, app, root, clock, owners, tokens, clients, run_id)
        for owner in (0, 1):
            harness.call("GET", "/api/me/medications", owner)
        yield harness


def test_live025_conflict_prn_retirement_and_b14_history(live025):
    h = live025
    h.clock.moment = datetime.now(UTC) - timedelta(minutes=2)
    name = h.run_id + " reviewed synthetic oral product"
    first = h.draft(name)
    second = h.draft(name, prn=True, amount=2)
    repos = build_supabase_repositories(h.clients[0])
    row = repos.regimens.get(h.owners[0], UUID(first["regimen_id"]))
    assert row is not None
    # Reviewed source alone does not authorize activation without B14.
    with pytest.raises(ValidationError):
        repos.regimens.update(row.model_copy(update={"state": RegimenState.ACTIVE, "effective_from": h.clock.now()}))
    challenge = h.challenge(first)
    h.activate(challenge)
    h.clock.moment = datetime.now(UTC)
    due = h.call("GET", "/api/doses/due", params={"regimen_id": first["regimen_id"]})
    assert bool(due.get("occurrence_id")), "Expected actual synthetic scheduled occurrence"
    path = f"/api/doses/{due['occurrence_id']}/report"
    body = {"regimen_id": first["regimen_id"], "intake_status": "taken", "idempotency_key": h.run_id + "-dose"}
    assert h.app.post(path, headers=h.headers(), json=body).status_code == 422
    report_challenge = h.call("POST", path + "/challenge", json=body)
    body["challenge_id"] = report_challenge["challenge_id"]
    event = h.call("POST", path, json=body)
    assert h.call("POST", path, json=body)["event_id"] == event["event_id"]
    stored = h.clients[0].rows("dose_events", id=f"eq.{event['event_id']}")
    assert len(stored) == 1 and stored[0]["ingestion_proven"] is False
    pending = h.challenge(second)
    conflict = h.app.post(
        "/api/medications/activate",
        headers=h.headers(),
        json={
            k: pending[k]
            for k in ("regimen_id", "challenge_id", "session_id", "session_state", "session_state_version")
        },
    )
    assert conflict.status_code == 409 and conflict.json()["code"] == "REGIMEN_OVERLAP"
    assert h.clients[0].rows("confirmation_challenges", id=f"eq.{pending['challenge_id']}")[0]["consumed_at"] is None
    rejected = h.app.post(
        "/api/medications/drafts",
        headers=h.headers(),
        json={"medication_name": name, "dose_amount": 3, "dose_unit": "tablet"},
    )
    assert rejected.status_code == 409
    # Test the DB boundary too; the failed HTTP activation explicitly confirmed
    # its challenge, but the database still refuses the overlapping PRN plan.
    second_row = repos.regimens.get(h.owners[0], UUID(second["regimen_id"]))
    with pytest.raises(RegimenOverlapError):
        repos.regimens.update(
            second_row.model_copy(
                update={
                    "state": RegimenState.ACTIVE,
                    "effective_from": h.clock.now(),
                    "confirmation_challenge_id": UUID(pending["challenge_id"]),
                }
            )
        )
    h.call("POST", f"/api/medications/{first['regimen_id']}/end", json={"confirmed": True})
    h.activate(pending)
    replacement = h.clients[0].rows("regimen_versions", id=f"eq.{second['regimen_id']}")[0]
    with pytest.raises(ValidationError):
        h.clients[0].request(
            "PATCH", "/rest/v1/regimen_versions", params={"id": f"eq.{replacement['id']}"}, body={"dose_amount": 99}
        )
    history = h.call("GET", "/api/me/regimens")
    states = {r["regimen_id"]: r["state"] for r in history}
    assert states[first["regimen_id"]] == "ended" and states[second["regimen_id"]] == "active"
    assert h.clients[0].rows("dose_events", id=f"eq.{event['event_id']}") == stored
    # A new request/view still reads persisted history, not transient app state.
    assert h.call("GET", "/api/me/regimens") == history


def test_live025_two_independent_clients_concurrent_database_activation(live025):
    h = live025
    h.clock.moment = datetime.now(UTC) - timedelta(minutes=2)
    name = h.run_id + " concurrent synthetic product"
    drafts = [h.draft(name), h.draft(name, amount=2)]
    challenges = [h.challenge(d) for d in drafts]
    principal = h.root.auth.resolve(authorization=h.headers()["Authorization"], client_id=None)
    scoped = h.root.patient_factory(principal)
    try:
        for challenge in challenges:
            scoped.enrollment.confirm_challenge(patient_id=h.owners[0], challenge_id=UUID(challenge["challenge_id"]))
    finally:
        scoped.close_request()
    barrier = Barrier(2, timeout=20)

    class RealPatchGate(httpx.HTTPTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            if request.method == "PATCH" and request.url.path.endswith("/regimen_versions"):
                barrier.wait()
            return super().handle_request(request)

    def activate(index: int) -> str:
        with httpx.Client(transport=RealPatchGate(), timeout=15) as http:
            client = SupabaseDataClient(
                base_url=h.settings.require_supabase_url(),
                publishable_key=h.settings.require_publishable_key(),
                access_token=h.tokens[0],
                patient_id=h.owners[0],
                client=http,
            )
            repos = build_supabase_repositories(client)
            row = repos.regimens.get(h.owners[0], UUID(drafts[index]["regimen_id"]))
            try:
                repos.regimens.update(
                    row.model_copy(
                        update={
                            "state": RegimenState.ACTIVE,
                            "effective_from": h.clock.now(),
                            "confirmation_challenge_id": UUID(challenges[index]["challenge_id"]),
                        }
                    )
                )
                return "active"
            except RegimenOverlapError:
                return "database_P7501_conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(activate, (0, 1)))
    assert sorted(outcomes) == ["active", "database_P7501_conflict"]
    rows = [h.clients[0].rows("regimen_versions", id=f"eq.{d['regimen_id']}")[0] for d in drafts]
    assert sum(r["state"] == "active" for r in rows) == 1
    winner = next(r for r in rows if r["state"] == "active")
    for row, challenge in zip(rows, challenges, strict=True):
        consumed = h.clients[0].rows("confirmation_challenges", id=f"eq.{challenge['challenge_id']}")[0]["consumed_at"]
        assert (consumed is not None) == (row["state"] == "active")
    # This test deliberately targets the Data API boundary, not the entire
    # application scheduling flow. Retire its winner through the public API.
    h.clock.moment = datetime.now(UTC)
    h.call("POST", f"/api/medications/{winner['id']}/end", json={"confirmed": True})


def test_live025_cross_patient_rls_and_same_name_does_not_block_other_owner(live025):
    h = live025
    h.clock.moment = datetime.now(UTC) - timedelta(minutes=2)
    name = h.run_id + " patient-isolated synthetic product"
    first = h.draft(name)
    h.activate(h.challenge(first))
    second = h.draft(name, owner=1)
    h.activate(h.challenge(second, owner=1), owner=1)
    assert h.clients[1].rows("regimen_versions", id=f"eq.{first['regimen_id']}") == []
    assert h.clients[0].rows("regimen_versions", id=f"eq.{second['regimen_id']}") == []
    assert (
        h.clients[1].request(
            "PATCH", "/rest/v1/regimen_versions", params={"id": f"eq.{first['regimen_id']}"}, body={"state": "ended"}
        )
        == []
    )
    with pytest.raises((ValidationError, AuthenticationRequiredError)):
        h.clients[1].request(
            "POST",
            "/rest/v1/patient_medications",
            body={
                "id": str(uuid4()),
                "patient_id": str(h.owners[0]),
                "display_name": "DEMO forbidden foreign write",
                "demo_only": True,
            },
        )
    assert (
        h.app.post(
            f"/api/medications/{first['regimen_id']}/end", headers=h.headers(1), json={"confirmed": True}
        ).status_code
        == 404
    )
    assert h.clients[0].rows("regimen_versions", id=f"eq.{first['regimen_id']}")[0]["state"] == "active"
