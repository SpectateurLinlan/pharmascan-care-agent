"""DEMO_ONLY isolated PostgreSQL: same queue/Worker, no external notifications."""

import os
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.application.notification_worker import NotificationWorker
from app.contracts.notifications import DeliveryResult
from app.infrastructure.notification_jobs import PostgresNotificationJobs
from app.infrastructure.postgres_db import PostgresDatabase
from app.transport.dispatcher import create_dispatcher_app
from app.transport.worker_container import build_worker_dispatch
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from .test_conversation_threads_sql import A, B, owner
from .test_conversation_threads_sql import db as db
from .test_reminder_delivery import subscription
from .test_synthetic_dispatch import PATH, TOKEN, headers

pytestmark = pytest.mark.skipif(not os.environ.get("THREADS_TEST_DSN"), reason="isolated localhost PostgreSQL required")


def jobs(db, patient=A, synthetic=True):
    return PostgresNotificationJobs(
        PostgresDatabase(dsn=f"postgresql://postgres@127.0.0.1:55439/{db.info.dbname}"),
        patient_scope=patient,
        synthetic_only=synthetic,
        include_late_reports=True,
        extended_tasks=True,
        multiple_reminders=True,
    )


def mark(db, value):
    # Auth shim only, never executed against a real Supabase project.
    db.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS raw_app_meta_data jsonb DEFAULT '{}'::jsonb")
    db.execute("UPDATE auth.users SET raw_app_meta_data=%s WHERE id=%s", (Jsonb(value), A))


def fingerprint(db, patient):
    return db.execute(
        "select coalesce(jsonb_agg(to_jsonb(d) order by id),'[]') from notification_deliveries d where patient_id=%s",
        (patient,),
    ).fetchone()[0]


@pytest.mark.parametrize("metadata", [{}, {"demo_only": False}, {"demo_only": "true"}])
def test_unverified_account_fails_before_queue_changes(db, metadata):
    mark(db, metadata)
    before = fingerprint(db, B)
    scoped = jobs(db)
    with pytest.raises(ValueError, match="admin-verified"):
        scoped.patients()
    with pytest.raises(ValueError, match="admin-verified"):
        scoped.claim(db.execute("select clock_timestamp()").fetchone()[0])
    assert fingerprint(db, B) == before


def test_scope_required_and_cross_owner_projection_rejected(db):
    with pytest.raises(ValueError, match="server-configured"):
        PostgresNotificationJobs(None, synthetic_only=True)
    mark(db, {"demo_only": True})
    now = db.execute("select clock_timestamp()").fetchone()[0]
    scoped = jobs(db)
    with pytest.raises(ValueError, match="scope mismatch"):
        scoped.sync_tasks(B, now)
    with pytest.raises(ValueError, match="scope mismatch"):
        scoped.sync(B, [], now)


def test_real_queue_scope_multiple_offsets_dedup_and_audit(db, monkeypatch):
    mark(db, {"demo_only": True})
    now = db.execute("select clock_timestamp()").fetchone()[0]
    for patient in [A, B]:
        db.execute("update patient_profiles set reminders_enabled=true where user_id=%s", (patient,))
        sub = subscription()
        db.execute(
            "insert into push_subscriptions(id,patient_id,endpoint,keys) values(%s,%s,%s,%s)",
            (uuid4(), patient, sub["endpoint"] + "/" + str(patient), Jsonb(sub["keys"])),
        )
        with owner(db, patient):
            db.execute(
                "select create_medication_care_task(%s)",
                (
                    Jsonb(
                        dict(
                            id=str(uuid4()),
                            title="DEMO_ONLY scoped test",
                            category="medication_review",
                            source="patient_reported",
                            notes="DEMO_ONLY",
                            due_at=(now + timedelta(hours=1, minutes=5)).isoformat(),
                            reminder_offsets=[60, 0],
                        )
                    ),
                ),
            )
        jobs(db, patient, synthetic=False).sync_tasks(patient, now)
    before_b = fingerprint(db, B)
    history = db.execute("select id,history,version from medication_care_tasks order by id").fetchall()
    scoped = jobs(db)
    assert [p["user_id"] for p in scoped.patients()] == [A]
    scoped.sync_tasks(A, now)
    assert fingerprint(db, B) == before_b

    class Clock:
        def now(self):
            return now + timedelta(minutes=6)

    class Sender:
        def __init__(self):
            self.sent = []

        def send(self, delivery):
            self.sent.append(delivery)
            return DeliveryResult(status="sent")

    sender = Sender()
    worker = NotificationWorker(scoped, sender, Clock())
    assert worker.deliver(5) == 1
    assert worker.deliver(5) == 0
    assert len(sender.sent) == 1
    assert fingerprint(db, B) == before_b
    # Actual composition + authenticated HTTP + SQL advisory lease + existing
    # projection/queue. Provider is the sole simulated external I/O here.
    from app.transport import worker_container

    monkeypatch.setattr(worker_container, "validate_vapid", lambda *args: None)
    monkeypatch.setattr(worker_container, "WebPushProvider", lambda **kwargs: sender)
    monkeypatch.setattr(worker_container, "SystemClock", Clock)
    settings = SimpleNamespace(
        enable_web_push=True,
        push_synthetic_patient_id=str(A),
        vapid_public_key="DEMO_ONLY",
        vapid_private_key="DEMO_ONLY",
        vapid_subject="DEMO_ONLY",
        require_database_url=lambda: f"postgresql://postgres@127.0.0.1:55439/{db.info.dbname}",
        enable_late_dose_reports=True,
        enable_care_task_followups=True,
        enable_multiple_care_reminders=True,
    )
    dispatch = build_worker_dispatch(settings, synthetic_only=True)
    client = TestClient(create_dispatcher_app(token=TOKEN, synthetic_runner=dispatch, wall_time=lambda: 2000))
    for _ in range(2):
        response = client.post(PATH, headers=headers())
        assert response.status_code == 200 and response.json() == {"status": "completed", "profiles": 1, "processed": 0}
    assert len(sender.sent) == 1 and fingerprint(db, B) == before_b
    assert db.execute("select id,history,version from medication_care_tasks order by id").fetchall() == history
    # A fabricated finish call for another account must not modify or disable it.
    foreign = jobs(db, B, synthetic=False).claim(Clock().now())
    assert foreign is not None
    before_b = fingerprint(db, B)
    with pytest.raises(ValueError, match="scope mismatch"):
        scoped.finish(foreign, DeliveryResult(status="expired_subscription"), Clock().now())
    assert fingerprint(db, B) == before_b
