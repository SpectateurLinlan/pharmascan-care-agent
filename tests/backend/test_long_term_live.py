"""Opt-in same-user Auth/JWT/RLS persistence, synthetic care data only.

No Stage2/Gemini calls unless separately enabled. Push queue tests never send.
"""

import base64
import os
from datetime import timedelta
from uuid import uuid4

import pytest
from app.domain.errors import AuthenticationRequiredError, ValidationError
from app.infrastructure.notification_jobs import PostgresNotificationJobs
from app.infrastructure.postgres_db import PostgresDatabase

from tests.backend.test_supabase_live import create_live_harness

pytestmark = pytest.mark.skipif(os.environ.get("RUN_SUPABASE_LIVE") != "1", reason="SUPABASE LIVE opt-in required")


def test_live_long_term_stock_barriers_followups_rls_and_queue():
    settings, identities, clients, app, clock = create_live_harness()
    a, b = identities
    ah = {"Authorization": "Bearer " + a.access_token}
    bh = {"Authorization": "Bearer " + b.access_token}

    def call(method, path, body=None, headers=None, **kwargs):
        response = app.request(method, path, headers=headers or ah, json=body, **kwargs)
        assert response.status_code == 200, f"HTTP {response.status_code} for {path}"
        return response.json()

    session = call("POST", "/api/demo/start", {"client_id": "DEMO-long-term"})
    draft = call(
        "POST",
        "/api/medications/drafts",
        {
            "medication_name": "DEMO Long-term Metformin 500 mg",
            "dose_amount": 1,
            "dose_unit": "tablet",
            "frequency_kind": "daily",
            "frequency_local_times": ["20:00"],
        },
    )
    call("POST", f"/api/medications/drafts/{draft['source_id']}/review", {"field_ids": None})
    challenge = call(
        "POST", f"/api/medications/drafts/{draft['regimen_id']}/challenge", params={"session_id": session["session_id"]}
    )
    call(
        "POST",
        "/api/medications/activate",
        {
            key: challenge[key]
            for key in ["regimen_id", "challenge_id", "session_id", "session_state", "session_state_version"]
        },
    )
    url = f"/api/me/inventory/{draft['medication_id']}"
    stock = {
        "id": str(uuid4()),
        "kind": "count",
        "quantity": 2,
        "unit": "tablet",
        "low_threshold": 7,
        "note": "DEMO count",
        "confirmed": True,
    }
    assert app.post(url, headers=ah, json={**stock, "confirmed": False}).status_code == 422
    first = call("POST", url, stock)
    assert first["estimated_remaining"] == 2 and first["low_stock"]
    assert len(call("POST", url, stock)["transactions"]) == 1
    assert app.post(url, headers=ah, json={**stock, "quantity": 6}).status_code == 422
    assert app.get(url, headers=bh).status_code == 404
    assert clients[1].rows("inventory_transactions") == []
    with pytest.raises((AuthenticationRequiredError, ValidationError)):
        clients[1].request(
            "POST",
            "/rest/v1/rpc/record_inventory_transaction",
            body={
                "p_medication_id": draft["medication_id"],
                "p_values": {key: value for key, value in stock.items() if key != "confirmed"},
            },
        )
    with pytest.raises((AuthenticationRequiredError, ValidationError)):
        clients[0].request("PATCH", "/rest/v1/inventory_transactions", body={"stock_after": 100})
    with pytest.raises((AuthenticationRequiredError, ValidationError)):
        clients[1].request("POST", "/rest/v1/inventory_transactions", body=clients[0].rows("inventory_transactions")[0])
    tasks = call("GET", "/api/me/care-tasks")
    assert len(tasks) == 1 and tasks[0]["category"] == "refill"
    contacted = {
        "id": str(uuid4()),
        "expected_version": 1,
        "status": "contacted",
        "confirmed": True,
        "notes": "DEMO pharmacy contacted",
    }
    assert call("POST", f"/api/me/care-tasks/{tasks[0]['id']}", contacted)["version"] == 2
    assert call("POST", f"/api/me/care-tasks/{tasks[0]['id']}", contacted)["version"] == 2
    barrier = {
        "id": str(uuid4()),
        "category": "running_out",
        "occurred_at": clock.now().isoformat(),
        "regimen_id": draft["regimen_id"],
        "description": "DEMO low supply",
        "chosen_action": "DEMO pharmacy contacted",
        "follow_up_task_id": tasks[0]["id"],
        "confirmed": True,
    }
    call("POST", "/api/me/adherence-barriers", barrier)
    call("POST", "/api/me/adherence-barriers", barrier)
    assert len(clients[0].rows("adherence_barriers")) == 1 and not clients[1].rows("adherence_barriers")
    assert app.post("/api/me/adherence-barriers", headers=bh, json=barrier).status_code == 404
    refill = {**stock, "id": str(uuid4()), "kind": "refill", "quantity": 30}
    assert call("POST", url, refill)["estimated_remaining"] == 32
    assert len(call("POST", url, refill)["transactions"]) == 2
    assert call("GET", "/api/me/care-tasks")[0]["status"] == "completed"
    # Cross-session: no memory seed. New session reads identical persisted facts.
    call("POST", "/api/demo/start", {"client_id": "DEMO-long-term-new-session"})
    assert call("GET", url)["estimated_remaining"] == 32
    task = call(
        "POST",
        "/api/me/care-tasks",
        {
            "id": str(uuid4()),
            "category": "medication_review",
            "title": "DEMO pharmacist review",
            "due_at": clock.now().isoformat(),
            "notes": "DEMO patient-reported plan",
            "medication_id": draft["medication_id"],
            "regimen_id": draft["regimen_id"],
            "confirmed": True,
        },
    )
    for offset, value in [(4, 130), (1, 125)]:
        call(
            "PUT",
            "/api/me/health-observations",
            {
                "id": str(uuid4()),
                "description": "DEMO measured BP",
                "occurred_at": (clock.now() - timedelta(days=offset)).isoformat(),
                "kind": "blood_pressure",
                "value": value,
                "secondary_value": 80,
                "unit": "mmHg",
                "confirmed": True,
            },
        )
    review = call("GET", "/api/me/medication-review", params={"days": 7})
    assert review["trends"][0]["count"] == 2 and review["trends"][0]["change"] == -5
    assert len(review["barriers"]) == 1 and review["source_records"][0]["source_document_id"] == draft["source_id"]
    assert (
        not clients[1].rows("medication_care_tasks")
        and call("GET", "/api/me/medication-review", headers=bh)["follow_ups"] == []
    )
    # Actual SQL scheduler/de-duplication, intentionally fake endpoint. Never send.
    from app.contracts.push import PushSubscriptionInput
    from app.infrastructure.push_subscriptions import SupabasePushSubscriptions

    subscriptions = SupabasePushSubscriptions(clients[0])
    subscription = subscriptions.save(
        a.user_id,
        PushSubscriptionInput(
            endpoint="https://fcm.googleapis.com/fcm/send/DEMO-care-" + uuid4().hex,
            keys={
                "auth": base64.urlsafe_b64encode(b"x" * 16).decode().rstrip("="),
                "p256dh": base64.urlsafe_b64encode(b"\x04" + b"x" * 64).decode().rstrip("="),
            },
        ),
    )
    try:
        jobs = PostgresNotificationJobs(PostgresDatabase(dsn=settings.require_database_url()), patient_scope=a.user_id)
        jobs.sync_tasks(a.user_id, clock.now())
        jobs.sync_tasks(a.user_id, clock.now())
        assert len(clients[0].rows("notification_deliveries")) == 1 and not clients[1].rows("notification_deliveries")
        # Cancel before claim: stale jobs must not be sent.
        change = {"id": str(uuid4()), "expected_version": task["version"], "status": "cancelled", "confirmed": True}
        call("POST", f"/api/me/care-tasks/{task['id']}", change)
        assert jobs.claim(clock.now()) is None
        assert clients[0].rows("notification_deliveries")[0]["status"] == "cancelled"
        # A second task can be claimed by the real queue. Explicitly acknowledge
        # an uncertain SIMULATED send outcome; no NotificationPort is called.
        from app.contracts.notifications import DeliveryResult

        second_values = {
            "id": str(uuid4()),
            "category": "medication_review",
            "title": "DEMO second review",
            "due_at": clock.now().isoformat(),
            "notes": "DEMO original",
            "confirmed": True,
        }
        second = call("POST", "/api/me/care-tasks", second_values)
        assert app.post("/api/me/care-tasks", headers=ah, json={**second_values, "notes": "changed"}).status_code == 422
        jobs.sync_tasks(a.user_id, clock.now())
        delivery = jobs.claim(clock.now())
        assert delivery is not None
        jobs.finish(delivery, DeliveryResult(status="uncertain_delivery"), clock.now())
        assert any(
            row["task_id"] == second["id"] and row["status"] == "failed"
            for row in clients[0].rows("notification_deliveries")
        )
    finally:
        subscriptions.revoke(a.user_id, subscription.id)
    assert not clients[0].rows("dose_events") and not clients[1].rows("dose_events")
    assert call("GET", "/api/me/medications")["medications"][0]["regimen_id"] == draft["regimen_id"]
