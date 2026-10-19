"""Real isolated PostgreSQL034; synthetic users/queue only, no provider sends."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.infrastructure.notification_jobs import PostgresNotificationJobs
from app.infrastructure.postgres_db import PostgresDatabase
from psycopg import errors
from psycopg.types.json import Jsonb

from .test_conversation_threads_sql import A, B, owner
from .test_conversation_threads_sql import db as db
from .test_regimen_successor_sql import _activate_as, _activate_initial, _make_plan
from .test_today_care_sql import task, update

pytestmark = pytest.mark.skipif(not os.environ.get("THREADS_TEST_DSN"), reason="isolated local PostgreSQL required")


@pytest.mark.parametrize("boundary", ["attention", "next_dose", "course_end"])
def test_worker_cancels_expired_dose_even_with_recent_snooze_delivery(db, boundary):
    now = db.execute("select clock_timestamp()").fetchone()[0]
    if boundary == "course_end":
        end = db.execute("select (clock_timestamp() at time zone 'Asia/Singapore')::date").fetchone()[0]
        plan, challenge, _, _, _, _ = _make_plan(db, A, course_end=end)
        db.execute("update regimen_versions set course_start_date=%s,course_end_date=%s where id=%s", (end, end, plan))
        _activate_as(db, A, plan, challenge)
    else:
        plan, _, _ = _activate_initial(db, A)
    rule = db.execute("select id from dose_rules where regimen_id=%s", (plan,)).fetchone()[0]
    due = now + (timedelta(seconds=1) if boundary == "course_end" else timedelta(days=1))
    now = due + timedelta(hours=24 if boundary == "course_end" else 3 if boundary == "attention" else 0.5)
    occurrence, subscription = uuid4(), uuid4()
    db.execute("update patient_profiles set reminders_enabled=true where user_id=%s", (A,))
    db.execute(
        "insert into push_subscriptions(id,patient_id,endpoint,keys) values(%s,%s,%s,%s)",
        (
            subscription,
            A,
            "https://fcm.googleapis.com/fcm/send/DEMO-" + str(subscription),
            Jsonb({"auth": "DEMO", "p256dh": "DEMO"}),
        ),
    )
    db.execute(
        "insert into dose_occurrences(id,patient_id,regimen_id,rule_id,due_at,generation_key) "
        "values(%s,%s,%s,%s,%s,%s)",
        (occurrence, A, plan, rule, due, "DEMO:" + str(occurrence)),
    )
    if boundary == "next_dose":
        db.execute(
            "insert into dose_occurrences(id,patient_id,regimen_id,rule_id,due_at,generation_key) "
            "values(%s,%s,%s,%s,%s,%s)",
            (uuid4(), A, plan, rule, now - timedelta(minutes=1), "DEMO:" + str(uuid4())),
        )
    if boundary == "course_end":
        with pytest.raises(errors.RaiseException), db.transaction():
            db.execute(
                "insert into dose_occurrences(id,patient_id,regimen_id,rule_id,due_at,generation_key) "
                "values(%s,%s,%s,%s,%s,%s)",
                (uuid4(), A, plan, rule, now, "DEMO:" + str(uuid4())),
            )
    delivery = db.execute(
        "insert into notification_deliveries(patient_id,occurrence_id,regimen_id,rule_id,subscription_id,"
        "slot,remind_at,next_attempt_at) values(%s,%s,%s,%s,%s,%s,%s,%s) returning id",
        (A, occurrence, plan, rule, subscription, "DEMO:recent-snooze", now, now),
    ).fetchone()[0]
    jobs = PostgresNotificationJobs(
        PostgresDatabase(dsn=f"postgresql://postgres@127.0.0.1:55439/{db.info.dbname}"),
        patient_scope=A,
        include_late_reports=True,
        extended_tasks=True,
    )
    jobs.claim(now)
    assert (
        db.execute("select status from notification_deliveries where id=%s", (delivery,)).fetchone()[0] == "cancelled"
    )


def test_multiple_offsets_persist_normalize_and_keep_audit(db):
    row = task(db, reminder_offsets=[0, 60, 1440, 60])
    assert row.reminder_offsets == [1440, 60, 0] and row.reminder_minutes == 1440
    assert row.history[0].reminder_offsets == [1440, 60, 0]
    edited = update(db, row, reminder_offsets=[180, 0])
    assert edited.version == 2 and edited.reminder_offsets == [180, 0]
    assert edited.history[0].reminder_offsets == [1440, 60, 0]
    assert edited.history[-1].reminder_offsets == [180, 0]
    with owner(db, B):
        assert db.execute("select count(*) from medication_care_tasks where id=%s", (row.id,)).fetchone()[0] == 0
        with pytest.raises(errors.InsufficientPrivilege), db.transaction():
            db.execute(
                "select update_medication_care_task(%s,%s)",
                (row.id, Jsonb(dict(id=str(uuid4()), expected_version=2, status="completed"))),
            )


@pytest.mark.parametrize("offsets", [[-1], [10081], [True], [1.5], [None], list(range(9))])
def test_invalid_offsets_rejected_atomically(db, offsets):
    with pytest.raises(errors.InvalidParameterValue):
        task(db, reminder_offsets=offsets)


def test_scalar_compatibility_and_idempotent_retry(db):
    row = task(db, reminder_minutes=30)
    assert row.reminder_offsets == [30]
    key = str(uuid4())
    first = update(db, row, id=key, reminder_offsets=[0, 60])
    retry = update(db, row, id=key, reminder_offsets=[60, 0])
    assert retry.version == first.version and len(retry.history) == 2
    scalar = update(db, first, reminder_minutes=None)
    assert scalar.reminder_offsets == [] and scalar.reminder_minutes is None


def test_worker_multiple_offsets_deduplicate_and_cancel(db):
    now = db.execute("select clock_timestamp()").fetchone()[0]
    db.execute("update patient_profiles set reminders_enabled=true where user_id=%s", (A,))
    subscription = uuid4()
    db.execute(
        "insert into push_subscriptions(id,patient_id,endpoint,keys) values(%s,%s,%s,%s)",
        (
            subscription,
            A,
            "https://fcm.googleapis.com/fcm/send/DEMO-" + str(subscription),
            Jsonb({"auth": "DEMO", "p256dh": "DEMO"}),
        ),
    )
    row = task(db, due_at=(now + timedelta(days=1, minutes=5)).isoformat(), reminder_offsets=[1440, 60, 0])
    jobs = PostgresNotificationJobs(
        PostgresDatabase(dsn=f"postgresql://postgres@127.0.0.1:55439/{db.info.dbname}"),
        patient_scope=A,
        include_late_reports=True,
        extended_tasks=True,
        multiple_reminders=True,
    )
    tick = now + timedelta(minutes=10)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: jobs.sync_tasks(A, tick), range(2)))
    queued = db.execute(
        "select slot from notification_deliveries where task_id=%s and subscription_id=%s", (row.id, subscription)
    ).fetchall()
    assert len(queued) == 3 and len(set(queued)) == 3
    changed = update(db, row, reminder_offsets=[0])
    jobs.sync_tasks(A, tick)
    assert jobs.claim(tick) is None
    assert (
        db.execute(
            "select count(*) from notification_deliveries where task_id=%s and subscription_id=%s and status='pending'",
            (row.id, subscription),
        ).fetchone()[0]
        == 1
    )
    update(db, changed, status="cancelled")
    assert jobs.claim(row.due_at) is None
    assert (
        db.execute(
            "select count(*) from notification_deliveries where task_id=%s and subscription_id=%s and status='pending'",
            (row.id, subscription),
        ).fetchone()[0]
        == 0
    )


def test_nonempty_multiple_rollback_is_guarded(db):
    task(db, reminder_offsets=[60, 0])
    with pytest.raises(errors.RaiseException):
        db.execute(Path("supabase/rollback/202610190034_multiple_care_reminders_down.sql").read_text())
    db.execute("ROLLBACK")
    assert db.execute(
        "select exists(select 1 from information_schema.columns where table_name='medication_care_tasks' "
        "and column_name='reminder_offsets')"
    ).fetchone()[0]
