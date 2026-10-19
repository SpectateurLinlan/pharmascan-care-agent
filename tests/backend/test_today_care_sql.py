"""Real disposable PostgreSQL: migrations, RPC, RLS, audit and the existing queue."""

import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.contracts.late_reports import LateReportInput, LateReportRecord
from app.contracts.long_term import CareTask
from app.infrastructure.notification_jobs import PostgresNotificationJobs
from app.infrastructure.postgres_db import PostgresDatabase
from psycopg import errors
from psycopg.types.json import Jsonb

from .test_conversation_threads_sql import A, B, owner
from .test_conversation_threads_sql import db as db
from .test_regimen_successor_sql import _activate_initial, _session

pytestmark = pytest.mark.skipif(not os.environ.get("THREADS_TEST_DSN"), reason="isolated localhost PostgreSQL required")


def task(c, **changes):
    now = c.execute("select clock_timestamp()").fetchone()[0]
    values = dict(
        id=str(uuid4()),
        title="DEMO review",
        category="medication_review",
        due_at=(now + timedelta(days=2)).isoformat(),
        notes="DEMO",
        source="patient_reported",
        reminder_minutes=60,
    )
    values.update(changes)
    with owner(c, A):
        row = c.execute("select create_medication_care_task(%s)", (Jsonb(values),)).fetchone()[0]
    return CareTask.model_validate(row)


def update(c, row, **changes):
    values = dict(id=str(uuid4()), expected_version=row.version, status="open")
    values.update(changes)
    with owner(c, A):
        result = c.execute("select update_medication_care_task(%s,%s)", (row.id, Jsonb(values))).fetchone()[0]
    return CareTask.model_validate(result)


def challenge(c, occurrence, plan, values):
    session = _session(c, A)
    identifier = uuid4()
    c.execute(
        "insert into confirmation_challenges(id,patient_id,session_id,session_state_version,action,regimen_id,"
        "occurrence_id,intended_intake_status,idempotency_key,token_hash,request_hash,issued_at,expires_at) "
        "values(%s,%s,%s,1,'record_self_report',%s,%s,%s,%s,%s,%s,now(),now()+interval '10 minutes')",
        (
            identifier,
            A,
            session,
            plan,
            occurrence,
            values.intake_status,
            values.binding_key(occurrence),
            uuid4().hex * 2,
            uuid4().hex * 2,
        ),
    )
    c.execute(
        "update confirmation_challenges set confirmed_at=clock_timestamp() where patient_id=%s and id=%s",
        (A, identifier),
    )
    return identifier


def report(c, occurrence, values, token, patient=A):
    with owner(c, patient):
        result = c.execute(
            "select record_late_dose_report(%s,%s,%s)", (occurrence, Jsonb(values.model_dump(mode="json")), token)
        ).fetchone()[0]
    return LateReportRecord.model_validate(result)


def test_development_rollback_and_reapply_are_empty_only(db):
    from psycopg import Rollback

    with db.transaction():
        for name in ["202610190033_late_dose_reports_down.sql", "202610190032_care_task_followup_ux_down.sql"]:
            db.execute(Path("supabase/rollback", name).read_text("utf-8").replace("BEGIN;", "").replace("COMMIT;", ""))
        assert db.execute("select to_regclass('public.effective_dose_events')").fetchone()[0] is None
        for name in ["202610190032_care_task_followup_ux.sql", "202610190033_late_dose_reports.sql"]:
            db.execute(
                Path("supabase/migrations", name).read_text("utf-8").replace("BEGIN;", "").replace("COMMIT;", "")
            )
        assert db.execute("select to_regclass('public.effective_dose_events')").fetchone()[0]
        raise Rollback()


def test_real_task_create_edit_complete_reopen_and_history(db):
    row = task(db)
    assert row.history[0].reminder_minutes == 60
    edited = update(db, row, title="DEMO changed", notes="DEMO bring list", reminder_minutes=30)
    assert edited.title == "DEMO changed" and edited.history[0].title == "DEMO review"
    done = update(db, edited, status="completed")
    reopened = update(db, done, status="open", reminder_minutes=None)
    assert reopened.version == 4 and len(reopened.history) == 4 and reopened.reminder_minutes is None
    with owner(db, B):
        assert db.execute("select count(*) from medication_care_tasks where id=%s", (row.id,)).fetchone()[0] == 0
        with pytest.raises(errors.InsufficientPrivilege), db.transaction():
            db.execute(
                "select update_medication_care_task(%s,%s)",
                (row.id, Jsonb(dict(id=str(uuid4()), expected_version=4, status="completed"))),
            )
    past = db.execute("select now()-interval '1 day'").fetchone()[0].isoformat()
    with pytest.raises(errors.InvalidParameterValue):
        task(db, due_at=past, reminder_minutes=None)
    historical = task(db, due_at=past, reminder_minutes=None, historical_entry=True)
    assert historical.historical_entry and historical.reminder_minutes is None
    with pytest.raises(errors.InvalidParameterValue):
        task(db, due_at=past, historical_entry=True, reminder_minutes=60)


@pytest.mark.parametrize("status", ["reported_taken", "reported_not_taken", "unsure"])
def test_real_late_report_confirmation_immutable_corrections_and_rls(db, status):
    plan, _, _ = _activate_initial(db, A)
    rule = db.execute("select id from dose_rules where patient_id=%s and regimen_id=%s", (A, plan)).fetchone()[0]
    occurrence = uuid4()
    due = db.execute("select clock_timestamp()").fetchone()[0]
    db.execute(
        "insert into dose_occurrences(id,patient_id,regimen_id,rule_id,due_at,generation_key) "
        "values(%s,%s,%s,%s,%s,%s)",
        (occurrence, A, plan, rule, due, "DEMO:" + str(occurrence)),
    )
    values = LateReportInput(
        id=uuid4(),
        intake_status=status,
        reason="forgot_to_record",
        actual_administration_at=due.replace(microsecond=0) if status == "reported_taken" else None,
    )
    # Whole-second actual may precede plan activation in this instant fixture; omit it here.
    values = values.model_copy(update={"actual_administration_at": None})
    token = challenge(db, occurrence, plan, values)
    with pytest.raises(errors.RaiseException):
        report(db, occurrence, values.model_copy(update={"notes": "tamper"}), token)
    saved = report(db, occurrence, values, token)
    assert not saved.ingestion_proven and saved.recorded_at >= due
    assert report(db, occurrence, values, token) == saved
    # A stale client cannot append an ordinary report after the confirmed late report.
    ordinary = LateReportInput(id=uuid4(), intake_status="reported_taken", reason="other")
    ordinary_token = challenge(db, occurrence, plan, ordinary)
    payload = {
        "id": str(ordinary.id),
        "patient_id": str(A),
        "regimen_id": str(plan),
        "occurrence_id": str(occurrence),
        "confirmation_challenge_id": str(ordinary_token),
        "event_time": db.execute("select clock_timestamp()").fetchone()[0].isoformat(),
        "intake_status": "reported_taken",
        "visual_status": "not_checked",
        "ingestion_proven": False,
        "idempotency_key": ordinary.binding_key(occurrence),
    }
    with owner(db, A):
        with pytest.raises((errors.InvalidParameterValue, errors.RaiseException)), db.transaction():
            db.execute("select record_confirmed_self_report(%s)", (Jsonb(payload),))
    assert (
        db.execute("select consumed_at from confirmation_challenges where id=%s", (ordinary_token,)).fetchone()[0]
        is None
    )
    with owner(db, A):
        result = db.execute(
            "select id,intake_status,reported_late from effective_dose_events where occurrence_id=%s", (occurrence,)
        ).fetchone()
        assert result == (saved.id, status, True)
        assert db.execute("select count(*) from audit_events where correlation_id=%s", (saved.id,)).fetchone()[0] == 1
        with pytest.raises(errors.InsufficientPrivilege), db.transaction():
            db.execute("update dose_report_entries set notes='tamper' where id=%s", (saved.id,))
    with owner(db, B):
        assert (
            db.execute("select count(*) from effective_dose_events where occurrence_id=%s", (occurrence,)).fetchone()[0]
            == 0
        )
    correction = LateReportInput(
        id=uuid4(), intake_status="unsure", reason="correcting_record", expected_report_id=saved.id
    )
    corrected = report(db, occurrence, correction, challenge(db, occurrence, plan, correction))
    assert corrected.version == 2
    assert (
        db.execute("select count(*) from dose_report_entries where occurrence_id=%s", (occurrence,)).fetchone()[0] == 2
    )
    assert db.execute("select count(*) from dose_events where occurrence_id=%s", (occurrence,)).fetchone()[0] == 0
    assert db.execute("select intake_status from dose_report_entries where id=%s", (saved.id,)).fetchone()[0] == status


def test_real_advance_reminder_queue_dedup_reschedule_and_cancel(db):
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
    row = task(db, due_at=(now + timedelta(hours=2)).isoformat(), reminder_minutes=60)
    jobs = PostgresNotificationJobs(
        PostgresDatabase(dsn=f"postgresql://postgres@127.0.0.1:55439/{db.info.dbname}"),
        patient_scope=A,
        include_late_reports=True,
        extended_tasks=True,
    )
    jobs.sync_tasks(A, now)
    jobs.sync_tasks(A, now)
    queued = db.execute("select remind_at from notification_deliveries where task_id=%s", (row.id,)).fetchall()
    assert queued == [(now + timedelta(hours=1),)]
    # Synthetic legacy queue state, not an actual notification send.
    db.execute("update notification_deliveries set slot='task:1',status='sent',attempts=1 where task_id=%s", (row.id,))
    updated = update(db, row, notes="DEMO note only")
    jobs.sync_tasks(A, now)
    assert db.execute("select count(*) from notification_deliveries where task_id=%s", (row.id,)).fetchone()[0] == 1
    assert db.execute(
        "select slot,status,attempts from notification_deliveries where task_id=%s", (row.id,)
    ).fetchone() == ("task:1", "sent", 1)
    changed = update(db, updated, due_at=(now + timedelta(hours=3)).isoformat(), reminder_minutes=30)
    jobs.sync_tasks(A, now)
    assert db.execute(
        "select remind_at from notification_deliveries where task_id=%s and status='pending'", (row.id,)
    ).fetchall() == [(now + timedelta(hours=2, minutes=30),)]
    update(db, changed, reminder_minutes=None)
    jobs.sync_tasks(A, now)
    assert (
        db.execute(
            "select count(*) from notification_deliveries where task_id=%s and status='pending'", (row.id,)
        ).fetchone()[0]
        == 0
    )
    assert jobs.claim(now) is None  # no NotificationPort/send performed


def test_concurrent_corrections_are_serialized_without_lost_history(db):
    from concurrent.futures import ThreadPoolExecutor

    import psycopg

    plan, _, _ = _activate_initial(db, A)
    rule = db.execute("select id from dose_rules where patient_id=%s and regimen_id=%s", (A, plan)).fetchone()[0]
    occurrence = uuid4()
    db.execute(
        "insert into dose_occurrences(id,patient_id,regimen_id,rule_id,due_at,generation_key) "
        "values(%s,%s,%s,%s,clock_timestamp(),%s)",
        (occurrence, A, plan, rule, "DEMO:" + str(occurrence)),
    )
    proposals = [
        LateReportInput(id=uuid4(), intake_status=status, reason="other") for status in ["reported_taken", "unsure"]
    ]
    tokens = [challenge(db, occurrence, plan, values) for values in proposals]
    dsn = f"postgresql://postgres@127.0.0.1:55439/{db.info.dbname}"

    def submit(index):
        with psycopg.connect(dsn, autocommit=True) as connection:
            try:
                report(connection, occurrence, proposals[index], tokens[index])
                return "saved"
            except errors.InvalidParameterValue:
                return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, [0, 1])) == ["saved", "stale"]
    assert (
        db.execute("select count(*) from dose_report_entries where occurrence_id=%s", (occurrence,)).fetchone()[0] == 1
    )
    assert (
        db.execute(
            "select count(*) from confirmation_challenges where id=ANY(%s) and consumed_at is not null", (tokens,)
        ).fetchone()[0]
        == 1
    )


def test_used_ledger_and_task_history_refuse_destructive_rollback(db):
    for name in ["202610190033_late_dose_reports_down.sql", "202610190032_care_task_followup_ux_down.sql"]:
        with pytest.raises(errors.RaiseException), db.transaction():
            db.execute(Path("supabase/rollback", name).read_text("utf-8").replace("BEGIN;", "").replace("COMMIT;", ""))


@pytest.mark.parametrize(
    "status,attempts,expected", [("pending", 2, "pending"), ("failed", 3, "failed"), ("sending", 1, "sending")]
)
def test_legacy_task_queue_keeps_retry_budget_and_terminal_states(db, status, attempts, expected):
    now = db.execute("select clock_timestamp()").fetchone()[0]
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
    row = task(db, due_at=(now + timedelta(hours=2)).isoformat(), reminder_minutes=60)
    db.execute(
        "insert into notification_deliveries(patient_id,task_id,subscription_id,slot,remind_at,"
        "next_attempt_at,status,attempts) "
        "values(%s,%s,%s,'task:1',%s,%s,%s,%s)",
        (A, row.id, subscription, now + timedelta(hours=1), now + timedelta(hours=1), status, attempts),
    )
    jobs = PostgresNotificationJobs(
        PostgresDatabase(dsn=f"postgresql://postgres@127.0.0.1:55439/{db.info.dbname}"),
        patient_scope=A,
        include_late_reports=True,
        extended_tasks=True,
    )
    jobs.sync_tasks(A, now)
    assert db.execute(
        "select slot,status,attempts from notification_deliveries where task_id=%s and subscription_id=%s",
        (row.id, subscription),
    ).fetchall() == [("task:1", expected, attempts)]


def test_030_only_schema_legacy_reads_and_worker_do_not_require_031_032_033(db):
    from contextlib import contextmanager

    from app.infrastructure.postgres_repos import PostgresDoseEventRepository
    from psycopg import Rollback
    from psycopg.rows import dict_row

    with db.transaction():
        # Existing tests may have used the new ledger. Use a clean disposable owner-free schema
        # snapshot by removing synthetic rows only inside this rolled-back test transaction.
        db.execute("SET LOCAL session_replication_role = replica")
        db.execute("DELETE FROM dose_report_entries")
        db.execute("DELETE FROM medication_care_tasks")
        db.execute("SET LOCAL session_replication_role = origin")
        for name in [
            "202610190033_late_dose_reports_down.sql",
            "202610190032_care_task_followup_ux_down.sql",
            "202610190031_medication_library_file_lifecycle_down.sql",
        ]:
            db.execute(Path("supabase/rollback", name).read_text("utf-8").replace("BEGIN;", "").replace("COMMIT;", ""))
        assert db.execute(
            "select to_regclass('public.effective_dose_events'),to_regclass('public.medication_library_files')"
        ).fetchone() == (None, None)

        @contextmanager
        def session(_patient=None):
            previous = db.row_factory
            db.row_factory = dict_row
            try:
                yield db
            finally:
                db.row_factory = previous

        class IsolatedConnection:
            transaction = staticmethod(session)

        events = PostgresDoseEventRepository(session)
        now = db.execute("select clock_timestamp()").fetchone()[0]
        events.list_for_patient(A, now - timedelta(days=7), now)
        events.find_by_occurrence(A, uuid4())
        jobs = PostgresNotificationJobs(IsolatedConnection(), patient_scope=A)
        jobs.sync_tasks(A, now)
        jobs.claim(now)
        # 033 is independently applicable on the real030 schema, without031 or032.
        db.execute(
            Path("supabase/migrations/202610190033_late_dose_reports.sql")
            .read_text("utf-8")
            .replace("BEGIN;", "")
            .replace("COMMIT;", "")
        )
        assert db.execute("select to_regclass('public.effective_dose_events')").fetchone()[0]
        PostgresDoseEventRepository(session, include_late_reports=True).list_for_patient(
            A, now - timedelta(days=7), now
        )
        jobs = PostgresNotificationJobs(IsolatedConnection(), patient_scope=A, include_late_reports=True)
        jobs.sync_tasks(A, now)
        jobs.claim(now)
        raise Rollback()


@pytest.mark.parametrize("changes", [{"reason": None}, {"reason": "unknown"}, {"intake_status": "missed"}])
def test_rpc_rejects_missing_reason_or_invalid_status_without_consuming_confirmation(db, changes):
    plan, _, _ = _activate_initial(db, A)
    rule = db.execute("select id from dose_rules where patient_id=%s and regimen_id=%s", (A, plan)).fetchone()[0]
    occurrence = uuid4()
    db.execute(
        "insert into dose_occurrences(id,patient_id,regimen_id,rule_id,due_at,generation_key) "
        "values(%s,%s,%s,%s,clock_timestamp(),%s)",
        (occurrence, A, plan, rule, "DEMO:" + str(occurrence)),
    )
    values = LateReportInput(id=uuid4(), intake_status="reported_taken", reason="forgot_to_record")
    token = challenge(db, occurrence, plan, values)
    payload = {**values.model_dump(mode="json"), **changes}
    with pytest.raises(
        (errors.RaiseException, errors.CheckViolation, errors.NotNullViolation, errors.InvalidParameterValue)
    ):
        with owner(db, A):
            db.execute("select record_late_dose_report(%s,%s,%s)", (occurrence, Jsonb(payload), token))
    assert (
        db.execute("select count(*) from dose_report_entries where occurrence_id=%s", (occurrence,)).fetchone()[0] == 0
    )
    assert db.execute("select consumed_at from confirmation_challenges where id=%s", (token,)).fetchone()[0] is None
