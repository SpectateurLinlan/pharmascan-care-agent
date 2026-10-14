"""REAL LIVE only when RUN_SUPABASE_LIVE=1. Tokens never leave process memory.

Creates real anonymous Auth identities and demo_only records. Append-only
clinical history is retained; only this test's synthetic Storage objects are
deleted through their owner's JWT. No privileged connection is used.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from app.config import Settings
from app.domain.errors import AuthenticationRequiredError, ValidationError
from app.infrastructure.supabase_data import SupabaseDataClient
from app.transport.app_factory import create_app
from app.transport.container import build_supabase_container
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(os.environ.get("RUN_SUPABASE_LIVE") != "1", reason="REAL LIVE opt-in required")


@pytest.mark.skipif(os.environ.get("RUN_STAGE2_LIVE") != "1", reason="REAL LIVE personal Stage2 opt-in required")
def test_live_personal_gallery_storage_embed_match_and_rls(course_live):
    import io

    from PIL import Image, ImageDraw

    _settings, identities, clients, app, _clock = course_live
    headers = {"Authorization": "Bearer " + identities[0].access_token}
    foreign_headers = {"Authorization": "Bearer " + identities[1].access_token}
    session = app.post("/api/demo/start", headers=headers, json={"client_id": "DEMO-personal-gallery"}).json()
    draft = app.post(
        "/api/medications/drafts",
        headers=headers,
        json={
            "medication_name": "DEMO synthetic Metformin",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_kind": "daily",
            "frequency_local_times": ["20:00"],
        },
    ).json()
    assert (
        app.post(
            f"/api/medications/drafts/{draft['source_id']}/review", headers=headers, json={"field_ids": None}
        ).status_code
        == 200
    )
    challenge = app.post(
        f"/api/medications/drafts/{draft['regimen_id']}/challenge",
        headers=headers,
        params={"session_id": session["session_id"]},
    ).json()
    activation = app.post(
        "/api/medications/activate",
        headers=headers,
        json={
            "regimen_id": draft["regimen_id"],
            "challenge_id": challenge["challenge_id"],
            "session_id": session["session_id"],
            "session_state": challenge["session_state"],
            "session_state_version": challenge["session_state_version"],
        },
    )
    assert activation.status_code == 200
    image = Image.new("RGB", (384, 384), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((110, 140, 275, 245), fill="#e0e0db", outline="#60605d", width=3)
    draw.line((145, 190, 240, 190), fill="#777777", width=2)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    photo = stream.getvalue()
    upload_headers = {**headers, "Content-Type": "image/png", "X-Stage2-Consent": "true", "X-Demo-Only": "true"}
    url = f"/api/evidence/gallery/{draft['medication_id']}/images"
    params = {
        "image_kind": "loose_pill",
        "source_description": "DEMO generated pill appearance",
        "reviewed": "true",
        "for_comparison": "true",
    }
    reference = app.post(url, params=params, headers=upload_headers, content=photo)
    assert reference.status_code == 200, "Real private reference upload failed"
    record = reference.json()
    assert record["eligibility"] == "eligible", "Real Stage2 embedding is not usable"
    image_id = record["id"]
    assert app.post(url, params=params, headers=upload_headers, content=photo).json()["id"] == image_id
    assert app.get(f"/api/evidence/images/{image_id}", headers=headers).content == photo
    assert app.get(f"/api/evidence/images/{image_id}", headers=foreign_headers).status_code == 404
    # Omit every patient WHERE on the direct normal JWT regression.
    assert clients[1].rows("medication_images", id=f"eq.{image_id}") == []
    assert clients[1].rows("image_embeddings", image_id=f"eq.{image_id}") == []
    rows = app.get("/api/evidence/gallery", headers=headers).json()
    assert next(row for row in rows if row["medication"]["id"] == draft["medication_id"])["eligible_count"] == 1
    comparison = app.post(
        "/api/evidence/check-dose", params={"regimen_id": draft["regimen_id"]}, headers=upload_headers, content=photo
    )
    assert comparison.status_code == 200, "Real personal matching failed"
    run = comparison.json()
    assert run["reference_ids"] == [image_id] and run["outcome"] is not None
    assert run["decision"] in {"match", "unknown", "ambiguous"}
    assert run["outcome"]["model_version"] and not run["safe_to_take"] and not run["ingestion_proven"]
    assert clients[0].rows("recognition_runs", id=f"eq.{run['id']}")
    assert clients[0].rows("dose_events", regimen_id=f"eq.{draft['regimen_id']}") == []
    for kind in ["package", "blister"]:
        saved = app.post(
            url, params={**params, "image_kind": kind, "for_comparison": "false"}, headers=upload_headers, content=photo
        )
        assert saved.status_code == 200 and saved.json()["eligibility"] == "associated"

    assert app.post(f"/api/evidence/images/{image_id}/retire", headers=foreign_headers).status_code == 404
    retired = app.post(f"/api/evidence/images/{image_id}/retire", headers=headers)
    assert retired.status_code == 200, "Retirement rejected: " + retired.json().get("message", "unknown")
    assert retired.json()["eligibility"] == "ineligible"
    assert app.post(f"/api/evidence/images/{image_id}/retire", headers=headers).json() == retired.json()
    assert clients[0].rows("image_embeddings", image_id=f"eq.{image_id}")
    # Retiring preserves original evidence but removes it from current matching.
    no_reference = app.post(
        "/api/evidence/check-dose", params={"regimen_id": draft["regimen_id"]}, headers=upload_headers, content=photo
    )
    assert no_reference.json()["decision"] == "missing_reference"
    forged = clients[0].rows("medication_images", id=f"eq.{image_id}")[0]["data"]
    forged["eligibility"] = "eligible"
    with pytest.raises(ValidationError):
        clients[0].request(
            "PATCH", "/rest/v1/medication_images", params={"id": f"eq.{image_id}"}, body={"data": forged}
        )


def test_live_reload_after_agent_session_expiry_preserves_patient_access(course_live):
    _settings, identities, clients, app, clock = course_live
    headers = {"Authorization": "Bearer " + identities[0].access_token}
    started = app.post("/api/demo/start", headers=headers, json={"client_id": "DEMO-expired-reload"})
    assert started.status_code == 200
    session_id = started.json()["session_id"]
    before = clients[0].rows("agent_sessions", id=f"eq.{session_id}")[0]
    clock.moment += timedelta(hours=3)
    resumed = app.post(
        "/api/demo/start", headers=headers, json={"client_id": "DEMO-expired-reload", "session_id": session_id}
    )
    assert resumed.status_code == 200, "Expired session must not block patient bootstrap"
    assert resumed.json()["session_id"] != session_id
    assert resumed.json()["patient_id"] == started.json()["patient_id"]
    assert clients[0].rows("agent_sessions", id=f"eq.{session_id}")[0] == before
    for path in ["/api/me/preferences", "/api/me/medications", "/api/me/regimens"]:
        assert app.get(path, headers=headers).status_code == 200


def test_live_concurrent_today_history_reminder_materialization_is_retry_safe(course_live):
    from concurrent.futures import ThreadPoolExecutor

    _settings, identities, clients, app, _clock = course_live
    headers = {"Authorization": "Bearer " + identities[0].access_token}
    session = app.post("/api/demo/start", headers=headers, json={"client_id": "DEMO-generation-race"}).json()
    local_time = (datetime.now(UTC) + timedelta(minutes=10)).astimezone(ZoneInfo("Asia/Singapore")).strftime("%H:%M")
    draft = app.post(
        "/api/medications/drafts",
        headers=headers,
        json={
            "medication_name": "DEMO concurrent medication",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_kind": "daily",
            "frequency_local_times": [local_time],
        },
    ).json()
    assert (
        app.post(
            f"/api/medications/drafts/{draft['source_id']}/review", headers=headers, json={"field_ids": None}
        ).status_code
        == 200
    )
    activation = app.post(
        f"/api/medications/drafts/{draft['regimen_id']}/challenge",
        headers=headers,
        params={"session_id": session["session_id"]},
    ).json()
    assert (
        app.post(
            "/api/medications/activate",
            headers=headers,
            json={
                key: activation[key]
                for key in ["regimen_id", "challenge_id", "session_id", "session_state", "session_state_version"]
            },
        ).status_code
        == 200
    )
    paths = [
        ("/api/doses/due", {"regimen_id": draft["regimen_id"]}),
        ("/api/me/dose-history", {"regimen_id": draft["regimen_id"]}),
        ("/api/reminders/alerts", {}),
    ] * 2

    def read(item):
        return app.get(item[0], headers=headers, params=item[1]).status_code

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(read, paths)) == [200] * 6
    rows = clients[0].rows("dose_occurrences", regimen_id="eq." + draft["regimen_id"])
    assert rows and len(rows) == len({row["generation_key"] for row in rows})
    assert not clients[0].rows("dose_events") and not clients[1].rows("dose_occurrences")


def test_live_health_notes_summary_profile_and_recent_chat_isolation(course_live):
    _settings, identities, clients, app, clock = course_live
    a, b = identities
    ah = {"Authorization": "Bearer " + a.access_token}
    bh = {"Authorization": "Bearer " + b.access_token}
    session = app.post("/api/demo/start", headers=ah, json={"client_id": "DEMO-health-review"}).json()
    assert app.put("/api/me/preferences", headers=ah, json={"display_name": "DEMO Alice"}).status_code == 200
    assert app.get("/api/me/preferences", headers=ah).json()["display_name"] == "DEMO Alice"
    assert app.get("/api/me/preferences", headers=bh).json()["display_name"] is None
    body = {
        "id": str(uuid4()),
        "occurred_at": clock.now().isoformat(),
        "description": "DEMO felt a little dizzy",
        "confirmed": False,
    }
    assert app.put("/api/me/health-observations", headers=ah, json=body).status_code == 422
    body["confirmed"] = True
    saved = app.put("/api/me/health-observations", headers=ah, json=body)
    assert saved.status_code == 200
    assert app.put("/api/me/health-observations", headers=ah, json=body).status_code == 200
    assert len(app.get("/api/me/health-observations", headers=ah).json()) == 1
    assert app.get("/api/me/health-observations", headers=bh).json() == []
    # Deliberately no application-side patient WHERE: real authenticated RLS.
    assert clients[1].rows("health_observations") == []
    assert len(clients[0].rows("health_observations")) == 1
    assert (
        clients[1].request(
            "PATCH",
            "/rest/v1/health_observations",
            params={"id": "eq." + body["id"]},
            body={"description": "DEMO forged"},
        )
        == []
    )
    assert clients[1].request("DELETE", "/rest/v1/health_observations", params={"id": "eq." + body["id"]}) == []
    forged = {**saved.json(), "id": str(uuid4())}
    with pytest.raises(AuthenticationRequiredError):
        clients[1].request("POST", "/rest/v1/health_observations", body=forged)
    assert (
        app.put("/api/me/health-observations", headers=ah, json={**body, "patient_id": str(b.user_id)}).status_code
        == 422
    )
    edited = {**body, "description": "DEMO feeling better"}
    assert app.put("/api/me/health-observations", headers=ah, json=edited).status_code == 200
    # Window end is exclusive; advance the injected server clock past the note.
    clock.moment += timedelta(seconds=1)
    summary = app.get("/api/me/review-summary", headers=ah, params={"period": "month"})
    assert summary.status_code == 200
    assert summary.json()["observations"][0]["description"] == "DEMO feeling better"
    assert summary.json()["reported_taken"] == 0
    assert app.get("/api/me/review-summary", headers=bh).json()["observations"] == []
    assert app.get(f"/api/agent/sessions/{session['session_id']}/recent-turns", headers=bh).status_code == 404
    assert app.get(f"/api/agent/sessions/{session['session_id']}/recent-turns", headers=ah).status_code == 200
    urgent = app.post(
        "/api/agent/messages",
        headers=ah,
        json={
            "session_id": session["session_id"],
            "text": "DEMO I took it but I cannot breathe",
            "client_turn_id": "DEMO-urgent",
            "slots": {},
        },
    )
    assert urgent.status_code == 200 and "995 in Singapore" in urgent.json()["message"]
    assert urgent.json()["pending_report"] is None and not clients[0].rows("dose_events")
    assert app.delete(f"/api/me/health-observations/{body['id']}", headers=bh).status_code == 404
    assert app.delete(f"/api/me/health-observations/{body['id']}", headers=ah).status_code == 200
    assert app.get("/api/me/health-observations", headers=ah).json() == []


def test_live_preferences_reload_and_rls_isolation(live):
    _settings, identities, clients, app, _clock = live
    headers = {"Authorization": "Bearer " + identities[0][1]}
    response = app.put("/api/me/preferences", headers=headers, json={"preferred_language": "zh", "text_size": "large"})
    assert response.status_code == 200
    assert response.json()["speech_locale"] == "zh-CN"
    assert app.get("/api/me/preferences", headers=headers).json()["preferred_language"] == "zh"
    # Intentionally no owner WHERE: profile RLS, not developer filtering.
    rows = clients[1].rows("patient_profiles")
    assert len(rows) == 1 and rows[0]["user_id"] == str(identities[1][0])
    assert rows[0]["language"] == "en"
    assert (
        clients[1].request(
            "PATCH", "/rest/v1/patient_profiles", params={"user_id": f"eq.{identities[0][0]}"}, body={"language": "en"}
        )
        == []
    )
    assert app.get("/api/me/preferences", headers=headers).json()["preferred_language"] == "zh"
    app.put("/api/me/preferences", headers=headers, json={"preferred_language": "en", "text_size": "standard"})


def test_live_reviewed_course_dates_persist_and_reject_outside_window(course_live):
    _settings, identities, clients, app, _clock = course_live
    headers = {"Authorization": "Bearer " + identities[0].access_token}
    today = datetime.now(ZoneInfo("Asia/Singapore")).date()

    def call(method, path, **kwargs):
        response = app.request(method, path, headers=headers, **kwargs)
        assert response.status_code == 200, f"HTTP {response.status_code} for {path}"
        return response.json()

    session = call("POST", "/api/demo/start", json={"client_id": "DEMO-course"})
    draft = call(
        "POST",
        "/api/medications/drafts",
        json={
            "medication_name": "DEMO finite-course Metformin",
            "dose_amount": 500,
            "dose_unit": "mg",
            "frequency_kind": "daily",
            "frequency_local_times": ["20:00"],
            "course_start_date": today.isoformat(),
            "course_end_date": today.isoformat(),
        },
    )
    call("POST", f"/api/medications/drafts/{draft['source_id']}/review", json={"field_ids": None})
    activation = call(
        "POST", f"/api/medications/drafts/{draft['regimen_id']}/challenge", params={"session_id": session["session_id"]}
    )
    assert activation["summary"]["course_end_date"] == today.isoformat()
    call(
        "POST",
        "/api/medications/activate",
        json={
            key: activation[key]
            for key in ["regimen_id", "challenge_id", "session_id", "session_state", "session_state_version"]
        },
    )
    reloaded = call("GET", "/api/me/medications")
    row = next(row for row in reloaded["medications"] if row["regimen_id"] == draft["regimen_id"])
    assert row["course_start_date"] == row["course_end_date"] == today.isoformat()
    assert not clients[1].rows("regimen_versions", id=f"eq.{draft['regimen_id']}")
    with pytest.raises(ValidationError):
        clients[0].request(
            "PATCH",
            "/rest/v1/regimen_versions",
            params={"id": f"eq.{draft['regimen_id']}"},
            body={"course_end_date": (today + timedelta(days=1)).isoformat()},
        )
    rule = clients[0].rows("dose_rules", regimen_id=f"eq.{draft['regimen_id']}")[0]
    with pytest.raises(ValidationError):
        clients[0].request(
            "POST",
            "/rest/v1/dose_occurrences",
            body={
                "id": str(uuid4()),
                "patient_id": str(identities[0].user_id),
                "regimen_id": draft["regimen_id"],
                "rule_id": rule["id"],
                "due_at": datetime.combine(
                    today + timedelta(days=1), datetime.min.time(), ZoneInfo("Asia/Singapore")
                ).isoformat(),
                "status": "scheduled",
                "generation_key": "DEMO-outside-course-" + uuid4().hex,
            },
        )


def test_live_patient_app_alerts_details_feedback_and_ownership(course_live):
    _settings, identities, clients, app, clock = course_live
    headers = {"Authorization": "Bearer " + identities[0].access_token}

    def call(method, path, **kwargs):
        response = app.request(method, path, headers=headers, **kwargs)
        assert response.status_code == 200, f"HTTP {response.status_code} for {path}"
        return response.json()

    session = call("POST", "/api/demo/start", json={"client_id": "DEMO-app-repair"})
    time = (datetime.now(UTC) - timedelta(minutes=1)).astimezone(ZoneInfo("Asia/Singapore")).strftime("%H:%M")
    draft = call(
        "POST",
        "/api/medications/drafts",
        json={
            "medication_name": "DEMO Metformin",
            "dose_amount": 500,
            "dose_unit": "mg",
            "food_instruction": "after food",
            "frequency_kind": "daily",
            "frequency_local_times": [time],
        },
    )
    call("POST", f"/api/medications/drafts/{draft['source_id']}/review", json={"field_ids": None})
    activation = call(
        "POST", f"/api/medications/drafts/{draft['regimen_id']}/challenge", params={"session_id": session["session_id"]}
    )
    call(
        "POST",
        "/api/medications/activate",
        json={
            key: activation[key]
            for key in ["regimen_id", "challenge_id", "session_id", "session_state", "session_state_version"]
        },
    )
    clock.moment = datetime.now(UTC)
    medication = call("GET", "/api/me/medications")["medications"][0]
    assert medication["dose_amount"] == 500 and medication["food_instruction"] == "after food"
    alerts = call("GET", "/api/reminders/alerts")
    assert len(alerts) == 1 and alerts[0]["dose_amount"] == 500
    b_headers = {"Authorization": "Bearer " + identities[1].access_token}
    assert app.get("/api/reminders/alerts", headers=b_headers).json() == []
    before = clients[0].rows("regimen_versions", id=f"eq.{draft['regimen_id']}")[0]
    call("POST", "/api/reminders", json={"occurrence_id": alerts[0]["occurrence_id"], "minutes": 15})
    assert call("GET", "/api/reminders/alerts") == []
    clock.moment += timedelta(minutes=16)
    snoozed = call("GET", "/api/reminders/alerts")
    assert len(snoozed) == 1 and snoozed[0]["key"] != alerts[0]["key"] and not clients[0].rows("dose_events")
    assert clients[0].rows("regimen_versions", id=f"eq.{draft['regimen_id']}")[0] == before
    payload = {"id": str(uuid4()), "category": "issue", "message": "DEMO synthetic app feedback"}
    submitted = call("POST", "/api/feedback", json=payload)
    assert submitted["status"] == "received" and call("POST", "/api/feedback", json=payload) == submitted
    assert clients[0].rows("patient_feedback")[0]["patient_id"] == str(identities[0].user_id)
    assert not clients[1].rows("patient_feedback")
    with pytest.raises(AuthenticationRequiredError):
        clients[1].request(
            "POST", "/rest/v1/patient_feedback", body={**payload, "patient_id": str(identities[0].user_id)}
        )
    assert (
        app.post(
            "/api/feedback", headers=headers, json={**payload, "patient_id": str(identities[1].user_id)}
        ).status_code
        == 422
    )


def test_live_session_context_survives_reload_and_foreign_session_is_not_reused(live):
    _settings, identities, clients, app, _clock = live
    headers = {"Authorization": "Bearer " + identities[0][1]}
    start = app.post("/api/demo/start", headers=headers, json={"client_id": "DEMO-context"}).json()
    reply = app.post(
        "/api/agent/messages",
        headers=headers,
        json={"session_id": start["session_id"], "text": "What medicine should I take tonight?"},
    )
    assert reply.status_code == 200
    rows = clients[0].rows("agent_sessions", id=f"eq.{start['session_id']}")
    assert rows[0]["context"]["version"] == 1 and len(rows[0]["context"]["recent_turns"]) == 1
    resumed = app.post(
        "/api/demo/start", headers=headers, json={"client_id": "DEMO-reload", "session_id": start["session_id"]}
    )
    assert resumed.status_code == 200 and resumed.json()["session_id"] == start["session_id"]
    foreign = app.post(
        "/api/demo/start",
        headers={"Authorization": "Bearer " + identities[1][1]},
        json={"client_id": "DEMO-B", "session_id": start["session_id"]},
    )
    assert foreign.status_code == 200 and foreign.json()["session_id"] != start["session_id"]
    assert clients[1].rows("agent_sessions", id=f"eq.{start['session_id']}") == []


class LiveClock:
    def __init__(self) -> None:
        self.moment = datetime.now(UTC) - timedelta(minutes=4)

    def now(self) -> datetime:
        return self.moment


@dataclass(frozen=True)
class LiveIdentity:
    user_id: UUID
    access_token: str = field(repr=False)

    def __iter__(self):
        yield self.user_id
        yield self.access_token

    def __getitem__(self, index: int):
        if index == 0:
            return self.user_id
        if index == 1:
            return self.access_token
        raise IndexError(index)


def create_live_harness():
    settings = replace(
        Settings.from_env(), persistence="supabase", auth_mode="supabase", model_provider="deterministic"
    )
    identities = []
    with httpx.Client(timeout=15) as client:
        for _ in range(2):
            response = client.post(
                settings.require_supabase_url() + "/auth/v1/signup",
                headers={"apikey": settings.require_publishable_key()},
                json={"data": {"demo_only": True, "test_session": "session_3d"}},
            )
            assert response.status_code == 200, "REAL LIVE anonymous signup blocked"
            payload = response.json()
            # Assertion introspection must never render a successful token
            # operand when a later anonymous-identity check fails.
            assert bool(payload.get("access_token")), "Anonymous session token missing"
            assert payload["user"]["is_anonymous"] is True
            identities.append(LiveIdentity(UUID(payload["user"]["id"]), payload["access_token"]))
    clock = LiveClock()
    container = build_supabase_container(settings=settings, clock=clock)
    app = TestClient(create_app(container=container), raise_server_exceptions=False)
    # Provision each owner's profile through the verified normal HTTP path.
    # Every selected live test must work independently of earlier test order.
    for identity in identities:
        initialized = app.get("/api/me/medications", headers={"Authorization": "Bearer " + identity.access_token})
        assert initialized.status_code == 200, "Authenticated owner setup blocked"
    clients = [
        SupabaseDataClient(
            base_url=settings.require_supabase_url(),
            publishable_key=settings.require_publishable_key(),
            patient_id=user,
            access_token=token,
        )
        for user, token in identities
    ]
    return settings, identities, clients, app, clock


@pytest.fixture(scope="module")
def live():
    return create_live_harness()


@pytest.fixture()
def course_live():
    # Finite-course enrollment must not alter another test's exact row counts.
    return create_live_harness()


def test_live_verified_auth_fastapi_and_atomic_confirmation(live):
    _settings, identities, clients, app, clock = live
    a, token = identities[0]
    headers = {"Authorization": "Bearer " + token}

    def call(method, path, **kwargs):
        response = app.request(method, path, headers=headers, **kwargs)
        assert response.status_code == 200, f"REAL LIVE {path}: HTTP {response.status_code}; {response.text}"
        return response.json()

    assert app.get("/api/me/medications").status_code == 401
    assert app.get("/api/me/medications", headers={"Authorization": "Bearer invalid"}).status_code == 401
    start = call("POST", "/api/demo/start", json={"client_id": "untrusted-body-id"})
    assert start["patient_id"] == str(a)
    local_time = (datetime.now(UTC) - timedelta(minutes=1)).astimezone(ZoneInfo("Asia/Singapore")).strftime("%H:%M")
    draft = call(
        "POST",
        "/api/medications/drafts",
        json={
            "medication_name": "DEMO synthetic medication",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_kind": "daily",
            "frequency_local_times": [local_time],
        },
    )
    call("POST", f"/api/medications/drafts/{draft['source_id']}/review", json={"field_ids": None})
    activation = call(
        "POST", f"/api/medications/drafts/{draft['regimen_id']}/challenge", params={"session_id": start["session_id"]}
    )
    call(
        "POST",
        "/api/medications/activate",
        json={
            "regimen_id": draft["regimen_id"],
            "challenge_id": activation["challenge_id"],
            "session_id": start["session_id"],
            "session_state": activation["session_state"],
            "session_state_version": activation["session_state_version"],
        },
    )
    clock.moment = datetime.now(UTC)
    due = call("GET", "/api/doses/due", params={"regimen_id": draft["regimen_id"]})
    assert due["occurrence_id"]
    path = f"/api/doses/{due['occurrence_id']}/report"
    body = {"regimen_id": draft["regimen_id"], "intake_status": "taken", "idempotency_key": "live-" + uuid4().hex}
    assert app.post(path, headers=headers, json=body).status_code == 422
    challenge = call("POST", path + "/challenge", json=body)
    reused = call("POST", path + "/challenge", json=body)
    assert reused["challenge_id"] == challenge["challenge_id"]
    assert reused["session_id"] == challenge["session_id"]
    pending = {
        "id": str(uuid4()),
        "patient_id": str(a),
        "regimen_id": draft["regimen_id"],
        "occurrence_id": due["occurrence_id"],
        "event_time": datetime.now(UTC).isoformat(),
        "intake_status": "reported_taken",
        "idempotency_key": body["idempotency_key"],
        "confirmation_challenge_id": challenge["challenge_id"],
    }
    agent_message = {
        "text": "I took it.",
        "client_turn_id": "DEMO-live-agent-report",
        "slots": {
            "regimen_id": draft["regimen_id"],
            "occurrence_id": due["occurrence_id"],
            "idempotency_key": body["idempotency_key"],
        },
    }
    agent = call("POST", "/api/agent/messages", json=agent_message)
    assert agent["mode"] == "deterministic_degraded" and agent["requires_confirmation"]
    assert agent["pending_report"]["challenge_id"] == challenge["challenge_id"]
    assert (
        call("POST", "/api/agent/messages", json=agent_message)["pending_report"]["challenge_id"]
        == challenge["challenge_id"]
    )
    # Database refuses a missing, unconfirmed or wrong-purpose challenge and
    # rolls back: the real owned occurrence remains open and no event exists.
    for challenge_id in (None, challenge["challenge_id"], activation["challenge_id"]):
        with pytest.raises(ValidationError):
            clients[0].request(
                "POST",
                "/rest/v1/rpc/record_confirmed_self_report",
                body={"p_event": {**pending, "confirmation_challenge_id": challenge_id}},
            )
    assert not clients[0].rows("dose_events", idempotency_key=f"eq.{body['idempotency_key']}")
    assert clients[0].rows("confirmation_challenges", id=f"eq.{challenge['challenge_id']}")[0]["consumed_at"] is None
    body["challenge_id"] = challenge["challenge_id"]
    event = call("POST", path, json=body)
    repeated = call("POST", path, json=body)
    assert repeated["already_recorded"] and repeated["event_id"] == event["event_id"]
    stored = clients[0].rows("dose_events", id=f"eq.{event['event_id']}")
    assert len(stored) == 1 and stored[0]["ingestion_proven"] is False
    assert stored[0]["intake_status"] == "reported_taken"
    assert stored[0]["visual_status"] == "not_checked"
    consumed = clients[0].rows("confirmation_challenges", id=f"eq.{challenge['challenge_id']}")
    assert consumed[0]["consumed_at"]
    # Replay the actual atomic RPC, including after consumption.
    replay = clients[0].request("POST", "/rest/v1/rpc/record_confirmed_self_report", body={"p_event": stored[0]})
    assert replay["id"] == event["event_id"]
    with pytest.raises(ValidationError):
        clients[0].request(
            "POST",
            "/rest/v1/rpc/record_confirmed_self_report",
            body={"p_event": {**stored[0], "intake_status": "unsure"}},
        )
    with pytest.raises(ValidationError):
        clients[1].request("POST", "/rest/v1/rpc/record_confirmed_self_report", body={"p_event": stored[0]})
    for user, user_token in identities:
        result = app.get(
            "/api/me/medications", headers={"Authorization": "Bearer " + user_token}, params={"client_id": str(a)}
        )
        assert result.status_code == 200
        assert result.json()["item_count"] == (1 if user == a else 0)


def test_live_rls_without_application_patient_filter(live):
    _settings, identities, clients, _app, _clock = live
    a, b = clients
    row_id = str(uuid4())
    body = {
        "id": row_id,
        "patient_id": str(identities[0][0]),
        "display_name": "DEMO RLS sentinel",
        "identity_status": "unverified",
        "demo_only": True,
    }
    a.request("POST", "/rest/v1/patient_medications", body=body)
    own_b = {**body, "id": str(uuid4()), "patient_id": str(identities[1][0])}
    b.request("POST", "/rest/v1/patient_medications", body=own_b)
    try:
        # Intentionally no patient_id filter. The provider executes auth.uid()
        # RLS independently of every application's ownership predicate.
        assert any(row["id"] == row_id for row in a.rows("patient_medications"))
        assert all(row["patient_id"] == str(identities[1][0]) for row in b.rows("patient_medications"))
        assert any(row["id"] == own_b["id"] for row in b.rows("patient_medications"))
        assert (
            b.request(
                "PATCH",
                "/rest/v1/patient_medications",
                params={"id": f"eq.{own_b['id']}"},
                body={"display_name": "DEMO B own update"},
            )[0]["display_name"]
            == "DEMO B own update"
        )
        assert not b.rows("patient_medications", id=f"eq.{row_id}")
        assert (
            b.request(
                "PATCH",
                "/rest/v1/patient_medications",
                params={"id": f"eq.{row_id}"},
                body={"display_name": "DEMO forged"},
            )
            == []
        )
        assert b.request("DELETE", "/rest/v1/patient_medications", params={"id": f"eq.{row_id}"}) == []
        with pytest.raises(AuthenticationRequiredError) as refused:
            b.request("POST", "/rest/v1/patient_medications", body={**body, "id": str(uuid4())})
        assert refused.value.code.value == "AUTH_REQUIRED"
        assert a.rows("patient_medications", id=f"eq.{row_id}")[0]["display_name"] == body["display_name"]
    finally:
        a.request("DELETE", "/rest/v1/patient_medications", params={"id": f"eq.{row_id}"})
        b.request("DELETE", "/rest/v1/patient_medications", params={"id": f"eq.{own_b['id']}"})


@pytest.mark.parametrize("bucket", ["medication-sources", "visual-references"])
def test_live_storage_owner_isolation(live, bucket):
    settings, identities, _clients, _app, _clock = live
    object_path = f"{identities[0][0]}/session-3d-{uuid4().hex}.txt"
    url = settings.require_supabase_url() + f"/storage/v1/object/{bucket}/{object_path}"
    headers = [
        {"apikey": settings.require_publishable_key(), "Authorization": "Bearer " + token}
        for _user, token in identities
    ]
    data = b"demo_only synthetic storage isolation fixture"
    with httpx.Client(timeout=15) as client:
        assert client.post(url, headers={**headers[0], "Content-Type": "text/plain"}, content=data).status_code == 200
        try:
            read_url = settings.require_supabase_url() + f"/storage/v1/object/authenticated/{bucket}/{object_path}"
            own = client.get(read_url, headers=headers[0])
            assert own.status_code == 200 and own.content == data
            assert client.get(read_url, headers=headers[1]).status_code >= 400
            forged_url = (
                settings.require_supabase_url()
                + f"/storage/v1/object/{bucket}/{identities[0][0]}/forged-{uuid4().hex}.txt"
            )
            assert (
                client.post(
                    forged_url,
                    headers={**headers[1], "Content-Type": "text/plain"},
                    content=b"demo_only forged owner path",
                ).status_code
                >= 400
            )
            assert (
                client.put(
                    url, headers={**headers[1], "Content-Type": "text/plain"}, content=b"demo_only forged"
                ).status_code
                >= 400
            )
            assert (
                client.post(
                    url,
                    headers={**headers[1], "Content-Type": "text/plain", "x-upsert": "true"},
                    content=b"demo_only forged",
                ).status_code
                >= 400
            )
            deletion = client.request(
                "DELETE",
                settings.require_supabase_url() + f"/storage/v1/object/{bucket}",
                headers=headers[1],
                json={"prefixes": [object_path]},
            )
            assert deletion.status_code >= 400 or deletion.json() == []
            assert client.get(read_url, headers=headers[0]).content == data
        finally:
            result = client.request(
                "DELETE",
                settings.require_supabase_url() + f"/storage/v1/object/{bucket}",
                headers=headers[0],
                json={"prefixes": [object_path]},
            )
            assert result.status_code == 200
        assert client.get(read_url, headers=headers[0]).status_code >= 400


@pytest.mark.skipif(os.environ.get("RUN_STAGE2_LIVE") != "1", reason="REAL LIVE Stage2 image opt-in required")
def test_live_stage2_synthetic_label_preview(live):
    import io

    from PIL import Image, ImageDraw

    _settings, identities, clients, app, _clock = live
    image = Image.new("RGB", (900, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.text(
        (30, 30),
        "DEMO ONLY - SYNTHETIC TEST LABEL\nTEST MEDICATION\nNo patient data\nManual review required",
        fill="black",
        font_size=28,
    )
    output = io.BytesIO()
    image.save(output, format="PNG")
    before = clients[0].rows("source_documents")
    response = app.post(
        "/api/sources/preview",
        params={"source_kind": "pharmacy_label"},
        headers={
            "Authorization": "Bearer " + identities[0][1],
            "Content-Type": "image/png",
            "X-Stage2-Consent": "true",
            "X-Demo-Only": "true",
        },
        content=output.getvalue(),
    )
    if response.status_code == 503:
        pytest.skip(
            "BLOCKED: REAL LIVE Stage2 label preview returned provider-unavailable; no extraction success claimed"
        )
    assert response.status_code == 200, f"REAL LIVE label preview HTTP {response.status_code}"
    payload = response.json()
    assert payload["review_required"] and payload["provider"] == "pharmascan:v0.8.0:/v1/read-label"
    for candidate in payload["candidates"]:
        assert not candidate["can_activate_regimen"]
        assert candidate["regimen_evidence"]["dose_amount"] is None
    assert clients[0].rows("source_documents") == before
    headers = {"Authorization": "Bearer " + identities[0][1]}
    draft = app.post(
        "/api/medications/drafts",
        headers=headers,
        json={
            "medication_name": "DEMO reviewed label medication",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_kind": "daily",
            "frequency_local_times": ["08:00"],
            "extraction_evidence": payload,
        },
    )
    assert draft.status_code == 200, "Source-backed manual draft rejected"
    source_id = draft.json()["source_id"]
    rows = clients[0].rows("source_documents", id=f"eq.{source_id}")
    assert rows[0]["extraction_evidence"] == payload and rows[0]["review_status"] == "extracted"
    assert clients[1].rows("source_documents", id=f"eq.{source_id}") == []
    with pytest.raises(ValidationError):
        clients[0].request(
            "PATCH", "/rest/v1/source_documents", params={"id": f"eq.{source_id}"}, body={"extraction_evidence": None}
        )
    reviewed = app.post(f"/api/medications/drafts/{source_id}/review", headers=headers, json={"field_ids": None})
    assert reviewed.status_code == 200
    assert clients[0].rows("source_documents", id=f"eq.{source_id}")[0]["extraction_evidence"] == payload
    assert clients[0].rows("regimen_versions", id=f"eq.{draft.json()['regimen_id']}")[0]["state"] == "draft"


def test_live_prn_confirmation_all_statuses_without_scheduled_occurrences(live):
    _settings, identities, clients, app, _clock = live
    headers = {"Authorization": "Bearer " + identities[0][1]}

    def call(method, path, **kwargs):
        response = app.request(method, path, headers=headers, **kwargs)
        assert response.status_code == 200, f"REAL LIVE PRN HTTP {response.status_code}; {response.text}"
        return response.json()

    start = call("POST", "/api/demo/start", json={"client_id": "DEMO-prn"})
    draft = call(
        "POST",
        "/api/medications/drafts",
        json={
            "medication_name": "DEMO PRN medicine",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "is_prn": True,
            "food_instruction": "DEMO reviewed as-needed condition",
        },
    )
    call("POST", f"/api/medications/drafts/{draft['source_id']}/review", json={"field_ids": None})
    activation = call(
        "POST", f"/api/medications/drafts/{draft['regimen_id']}/challenge", params={"session_id": start["session_id"]}
    )
    call(
        "POST",
        "/api/medications/activate",
        json={
            "regimen_id": draft["regimen_id"],
            "challenge_id": activation["challenge_id"],
            "session_id": start["session_id"],
            "session_state": activation["session_state"],
            "session_state_version": activation["session_state_version"],
        },
    )
    for choice, stored in (("taken", "reported_taken"), ("not_taken", "reported_not_taken"), ("unsure", "unsure")):
        body = {"regimen_id": draft["regimen_id"], "intake_status": choice, "idempotency_key": "DEMO-prn-" + choice}
        pending = call("POST", "/api/prn/report/challenge", json=body)
        assert pending["occurrence_id"] is None
        body["challenge_id"] = pending["challenge_id"]
        first = call("POST", "/api/prn/report", json=body)
        again = call("POST", "/api/prn/report", json=body)
        assert first["intake_status"] == stored and again["event_id"] == first["event_id"] and again["already_recorded"]
    assert not clients[0].rows("dose_occurrences", regimen_id=f"eq.{draft['regimen_id']}")
    history = call("GET", "/api/me/dose-history", params={"regimen_id": draft["regimen_id"]})
    assert history["item_count"] == 3 and all(entry["event_time"] for entry in history["entries"])


def test_live_reminder_is_scoped_snoozable_and_never_records_intake(live):
    _settings, identities, clients, app, clock = live
    clock.moment = datetime.now(UTC) - timedelta(minutes=4)
    headers = {"Authorization": "Bearer " + identities[1][1]}

    def call(method, path, **kwargs):
        response = app.request(method, path, headers=headers, **kwargs)
        assert response.status_code == 200, "Reminder journey failed"
        return response.json()

    start = call("POST", "/api/demo/start", json={"client_id": "DEMO-reminder"})
    time = (clock.now() + timedelta(minutes=1)).astimezone(ZoneInfo("Asia/Singapore")).strftime("%H:%M")
    draft = call(
        "POST",
        "/api/medications/drafts",
        json={
            "medication_name": "DEMO reminder medicine",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_kind": "daily",
            "frequency_local_times": [time],
        },
    )
    call("POST", f"/api/medications/drafts/{draft['source_id']}/review", json={"field_ids": None})
    activation = call(
        "POST", f"/api/medications/drafts/{draft['regimen_id']}/challenge", params={"session_id": start["session_id"]}
    )
    call(
        "POST",
        "/api/medications/activate",
        json={
            "regimen_id": draft["regimen_id"],
            "challenge_id": activation["challenge_id"],
            "session_id": start["session_id"],
            "session_state": activation["session_state"],
            "session_state_version": activation["session_state_version"],
        },
    )
    clock.moment = datetime.now(UTC)
    due = call("GET", "/api/doses/due", params={"regimen_id": draft["regimen_id"]})
    occurrence = due["occurrence_id"]
    assert occurrence
    before_regimens = clients[1].rows("regimen_versions")
    before_events = clients[1].rows("dose_events")
    first = call("POST", "/api/reminders", json={"occurrence_id": occurrence, "minutes": 15})
    updated = call("POST", "/api/reminders", json={"occurrence_id": occurrence, "minutes": 30})
    assert first["occurrence_id"] == updated["occurrence_id"] and first["remind_at"] != updated["remind_at"]
    assert len(clients[1].rows("dose_reminders")) == 1
    assert clients[0].rows("dose_reminders") == []  # deliberately no application owner WHERE
    cross = app.post(
        "/api/reminders",
        headers={"Authorization": "Bearer " + identities[0][1]},
        json={"occurrence_id": occurrence, "minutes": 15},
    )
    assert cross.status_code == 404
    assert (
        app.post("/api/reminders", headers=headers, json={"occurrence_id": occurrence, "minutes": 0}).status_code == 422
    )
    with pytest.raises((AuthenticationRequiredError, ValidationError)):
        clients[0].request("POST", "/rest/v1/dose_reminders", body=updated)
    assert (
        clients[0].request(
            "PATCH",
            "/rest/v1/dose_reminders",
            params={"occurrence_id": f"eq.{occurrence}"},
            body={"remind_at": first["remind_at"]},
        )
        == []
    )
    assert datetime.fromisoformat(clients[1].rows("dose_reminders")[0]["remind_at"]) == datetime.fromisoformat(
        updated["remind_at"]
    )
    agent = call(
        "POST",
        "/api/agent/messages",
        json={
            "text": "Remind me again in 20 minutes.",
            "session_id": start["session_id"],
            "client_turn_id": "DEMO-reminder-turn",
        },
    )
    assert any(
        trace["tool_name"] == "create_reminder" and trace["status"] == "success" for trace in agent["tool_traces"]
    )
    assert clients[1].rows("regimen_versions") == before_regimens
    assert clients[1].rows("dose_events") == before_events
    pending = call(
        "POST",
        "/api/agent/messages",
        json={"text": "I took it.", "session_id": start["session_id"], "client_turn_id": "DEMO-reminder-report"},
    )
    assert pending["pending_report"] and pending["requires_confirmation"]
    assert clients[1].rows("dose_events") == before_events
    assert call("GET", "/api/reminders")[0]["is_due"] is False
    clock.moment += timedelta(minutes=21)
    assert call("GET", "/api/reminders")[0]["is_due"] is True
    assert clients[1].rows("dose_events") == before_events
    assert clients[1].rows("regimen_versions") == before_regimens


def test_live_stage2_visual_check_is_evidence_not_medication_authority(live):
    import io

    from PIL import Image, ImageDraw

    _settings, identities, clients, app, _clock = live
    image = Image.new("RGB", (320, 320), "white")
    ImageDraw.Draw(image).ellipse((100, 120, 220, 200), fill="#eeeeee", outline="#777777", width=3)
    output = io.BytesIO()
    image.save(output, format="PNG")
    before = clients[0].rows("dose_events")
    response = app.post(
        "/api/visual-check",
        headers={
            "Authorization": "Bearer " + identities[0][1],
            "Content-Type": "image/png",
            "X-Stage2-Consent": "true",
            "X-Demo-Only": "true",
        },
        content=output.getvalue(),
    )
    assert response.status_code == 200
    result = response.json()
    assert result["decision"] in {"unknown", "ambiguous"}
    assert not result["comparison_available"] and not result["safe_to_take_confirmed"]
    assert not result["ingestion_proven"] and clients[0].rows("dose_events") == before


def test_live_atomic_demo_quota_no_direct_counter_edit_or_cross_patient_access(live):
    from concurrent.futures import ThreadPoolExecutor

    from app.infrastructure.quota_repos import SupabaseQuota

    _settings, identities, clients, _app, _clock = live
    a, b = identities[0][0], identities[1][0]
    quota = SupabaseQuota(clients[0])
    # Accounting RPCs are real; model attempts/completion are SYNTHETIC here.
    with ThreadPoolExecutor(max_workers=8) as pool:
        reservations = list(pool.map(lambda i: quota.reserve(a, f"DEMO-atomic-{i}"), range(24)))
    reserved = [row for row in reservations if row.state == "reserved"]
    assert len(reserved) == 20
    for row in reserved:
        quota.model_request(a, row)
        quota.finish(a, row, True)
    assert quota.usage(a).llm_user_turns == 20 and quota.reserve(a, "DEMO-extra").state == "exhausted"
    assert SupabaseQuota(clients[1]).usage(b).llm_user_turns == 0
    assert clients[1].rows("demo_ai_usage", patient_id=f"eq.{a}") == []
    with pytest.raises((AuthenticationRequiredError, ValidationError)):
        clients[0].request(
            "PATCH", "/rest/v1/demo_ai_usage", params={"patient_id": f"eq.{a}"}, body={"llm_user_turns": 0}
        )
    with pytest.raises((AuthenticationRequiredError, ValidationError)):
        SupabaseQuota(clients[1]).finish(b, reserved[0], False)


@pytest.mark.skipif(os.environ.get("RUN_STAGE2_LIVE") != "1", reason="REAL source evidence opt-in required")
def test_live_progressive_source_tasks_are_owned_without_repository_patient_filter(course_live):
    from io import BytesIO

    from PIL import Image, ImageDraw, ImageFont

    _, identities, clients, app, _ = course_live
    image = Image.new("RGB", (1100, 450), "white")
    try:
        font = ImageFont.truetype("arial.ttf", 32)
    except OSError:
        font = ImageFont.load_default(size=32)
    ImageDraw.Draw(image).multiline_text(
        (35, 40),
        "DEMO ONLY synthetic box\nAmlodipine 5 mg\nTablets\nProduct information only",
        fill="black",
        font=font,
        spacing=20,
    )
    stream = BytesIO()
    image.save(stream, format="PNG")
    a = {"Authorization": "Bearer " + identities[0].access_token}
    b = {"Authorization": "Bearer " + identities[1].access_token}
    uploaded = app.post(
        f"/api/evidence/tasks/{uuid4()}/sources",
        params={"source_kind": "package"},
        headers={**a, "Content-Type": "image/png", "X-Stage2-Consent": "true", "X-Demo-Only": "true"},
        content=stream.getvalue(),
    )
    assert uploaded.status_code == 200, "REAL source task upload rejected"
    task = uploaded.json()
    assert task["status"] == "pending_information" and task["missing"]
    assert app.get(f"/api/evidence/tasks/{task['id']}", headers=a).json() == task
    assert app.get(f"/api/evidence/tasks/{task['id']}", headers=b).status_code == 404
    assert app.get(f"/api/evidence/tasks/{task['id']}/sources", headers=b).status_code == 404
    sources = app.get(f"/api/evidence/tasks/{task['id']}/sources", headers=a).json()
    assert len(sources) == 1 and sources[0]["recorded_at"] and sources[0]["provided_by"] == "patient"
    assert clients[1].rows("medication_evidence_tasks", id=f"eq.{task['id']}") == []
    assert clients[1].rows("medication_source_links", medication_id=f"eq.{task['medication_id']}") == []
    assert clients[1].rows("medication_images", medication_id=f"eq.{task['medication_id']}") == []
    assert (
        clients[1].request(
            "PATCH",
            "/rest/v1/medication_evidence_tasks",
            params={"id": f"eq.{task['id']}"},
            body={"data": task, "version": task["version"]},
        )
        == []
    )
    with pytest.raises((AuthenticationRequiredError, ValidationError)):
        clients[1].request(
            "POST",
            "/rest/v1/medication_evidence_tasks",
            body={
                "id": task["id"],
                "patient_id": str(identities[0].user_id),
                "medication_id": task["medication_id"],
                "data": task,
                "version": task["version"],
            },
        )
    assert app.get(f"/api/evidence/tasks/{task['id']}", headers=a).json() == task
    assert clients[0].rows("regimen_versions", patient_medication_id=f"eq.{task['medication_id']}") == []
    assert clients[0].rows("dose_events") == []
