"""Integrated031→032→033 via actual runner/ledger on disposable localhost PostgreSQL.

Synthetic owners, platform Auth/Storage shims. Never accepts a remote database.
"""

import hashlib
import json
import os
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import psycopg
import pytest
from app.infrastructure.postgres_db import PostgresDatabase
from app.infrastructure.postgres_migrations import (
    MigrationFile,
    applied_migrations,
    apply_recorded_migration,
    discover_migrations,
    ensure_ledger,
)
from psycopg import sql
from psycopg.rows import dict_row

from .test_conversation_threads_sql import A, B, initialize_platform

pytestmark = pytest.mark.skipif(not os.environ.get("THREADS_TEST_DSN"), reason="isolated localhost PostgreSQL required")


@pytest.fixture(scope="module")
def integrated_dsn():
    dsn = os.environ["THREADS_TEST_DSN"]
    assert urlparse(dsn).hostname == "127.0.0.1" and urlparse(dsn).port == 55441
    name = "mt_unified_" + uuid4().hex[:10]
    with psycopg.connect(dsn, autocommit=True) as admin:
        for role in ["authenticated", "anon", "service_role", "authenticator"]:
            if not admin.execute("select 1 from pg_roles where rolname=%s", (role,)).fetchone():
                admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    local = f"postgresql://postgres@127.0.0.1:55441/{name}"
    database = PostgresDatabase(dsn=local, statement_timeout_ms=30000)
    migrations = discover_migrations()
    try:
        with database.connect(autocommit=True) as db:
            identity = db.execute(
                "select host(inet_server_addr()) as host,inet_server_port() as port,"
                "current_setting('data_directory') as folder"
            ).fetchone()
            assert identity["host"] == "127.0.0.1" and identity["port"] == 55441
            assert Path(identity["folder"]).resolve() == Path("outputs/incident031/pgdata").resolve()
            initialize_platform(db)
            ensure_ledger(db)
            prior = tuple(item for item in migrations if item.version <= "202610190030")
            for index, item in enumerate(prior):
                assert apply_recorded_migration(db, item, prerequisites=prior[:index])
            assert len(applied_migrations(db)) == 30
            db.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO service_role")
        from scripts import db as runner

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(runner, "_settings", lambda: None)
            patch.setattr(runner, "_database", lambda _: database)
            with database.connect(autocommit=True) as db:
                db.execute(
                    "CREATE FUNCTION demo_fail_031_ledger() RETURNS trigger LANGUAGE plpgsql "
                    "AS $$BEGIN IF NEW.version='202610190031' THEN RAISE EXCEPTION 'DEMO'; END IF; RETURN NEW; END$$"
                )
                db.execute(
                    "CREATE TRIGGER demo_fail_031_ledger BEFORE INSERT ON core_schema_migrations "
                    "FOR EACH ROW EXECUTE FUNCTION demo_fail_031_ledger()"
                )
            assert runner.cmd_migrate(Namespace(only="202610190031")) == 4
            with database.connect(autocommit=True) as db:
                assert len(applied_migrations(db)) == 30
                assert (
                    db.execute("select to_regclass('medication_library_files') as relation").fetchone()["relation"]
                    is None
                )
                db.execute(
                    "DROP TRIGGER demo_fail_031_ledger ON core_schema_migrations; DROP FUNCTION demo_fail_031_ledger()"
                )
            # The runner itself, not manual ledger inserts, applies this exact ordered stage.
            for version in ["202610190031", "202610190032", "202610190033"]:
                assert runner.cmd_migrate(Namespace(only=version)) == 0
            assert runner.cmd_migrate(Namespace(only="202610190033")) == 0
        with database.connect(autocommit=True) as db:
            ledger = applied_migrations(db)
            assert ledger == {item.version: item.sha256 for item in migrations}
            output = Path("outputs/unified-local-rc/migration-stage.json")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(
                    {
                        "environment": "isolated localhost55441 PostgreSQL; synthetic platform shims",
                        "migration_count": len(ledger),
                        "ordered_stage": [item.label for item in migrations[-3:]],
                        "hashes": {item.version: item.sha256 for item in migrations[-3:]},
                        "ledger_matches": True,
                        "real031_ledger_failure_rolled_back_ddl": True,
                    },
                    indent=2,
                ),
                encoding="utf8",
            )
            for patient in [A, B]:
                db.execute("insert into auth.users(id) values(%s)", (patient,))
                db.execute("insert into patient_profiles(user_id) values(%s)", (patient,))
        yield local
    finally:
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


@pytest.fixture
def db(integrated_dsn):
    with psycopg.connect(integrated_dsn, autocommit=True) as connection:
        yield connection


def test_full_stage_objects_acl_and_rls(integrated_dsn):
    with psycopg.connect(integrated_dsn, autocommit=True, row_factory=dict_row) as db:
        names = [
            "medication_library_files",
            "medication_library_file_audit",
            "medication_image_audit",
            "dose_report_entries",
        ]
        rows = db.execute(
            "select relname,relrowsecurity,relforcerowsecurity from pg_class where relname=any(%s)", (names,)
        ).fetchall()
        assert len(rows) == 4 and all(row["relrowsecurity"] and row["relforcerowsecurity"] for row in rows)
        assert db.execute("select to_regclass('effective_dose_events') as relation").fetchone()["relation"]
        assert (
            db.execute(
                "select has_function_privilege('anon',"
                "'public.record_late_dose_report(uuid,jsonb,uuid)','EXECUTE') as allowed"
            ).fetchone()["allowed"]
            is False
        )
        assert (
            db.execute(
                "select has_function_privilege('service_role',"
                "'public.manage_personal_gallery_image(uuid,text,integer,text,text,boolean)','EXECUTE') as allowed"
            ).fetchone()["allowed"]
            is False
        )


def synthetic_migration(version, body):
    text = "BEGIN;\n" + body + "\nCOMMIT;\n"
    return MigrationFile(
        version=version,
        name="DEMO_atomic",
        path=Path("DEMO.sql"),
        sql=text,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
    )


def test_ledger_failure_rolls_back_ddl_then_retry_is_idempotent(integrated_dsn):
    migration = synthetic_migration("DEMO_atomic_01", "CREATE TABLE public.demo_atomic_probe(id integer);")
    with psycopg.connect(integrated_dsn, autocommit=True, row_factory=dict_row) as db:
        db.execute(
            "CREATE FUNCTION public.demo_reject_ledger() RETURNS trigger LANGUAGE plpgsql "
            "AS $$BEGIN RAISE EXCEPTION 'DEMO ledger failure'; END$$"
        )
        db.execute(
            "CREATE TRIGGER demo_reject_ledger BEFORE INSERT ON core_schema_migrations "
            "FOR EACH ROW EXECUTE FUNCTION demo_reject_ledger()"
        )
        with pytest.raises(psycopg.errors.RaiseException):
            apply_recorded_migration(db, migration)
        assert db.execute("select to_regclass('demo_atomic_probe') as relation").fetchone()["relation"] is None
        assert migration.version not in applied_migrations(db)
        db.execute("DROP TRIGGER demo_reject_ledger ON core_schema_migrations; DROP FUNCTION demo_reject_ledger()")
        assert apply_recorded_migration(db, migration)
        assert not apply_recorded_migration(db, migration)
        assert applied_migrations(db)[migration.version] == migration.sha256


def test_concurrent_migration_submissions_apply_once(integrated_dsn):
    migration = synthetic_migration("DEMO_atomic_02", "CREATE TABLE public.demo_concurrent_probe(id integer);")

    def apply(_):
        with psycopg.connect(integrated_dsn, autocommit=True, row_factory=dict_row) as db:
            return apply_recorded_migration(db, migration)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(apply, range(2))) == [False, True]


@pytest.mark.parametrize("body", ["COMMIT; CREATE TABLE demo_escape(id int);", "ROLLBACK;", "BEGIN; SELECT 1;"])
def test_nested_transaction_escape_rejected_without_ddl(integrated_dsn, body):
    with psycopg.connect(integrated_dsn, autocommit=True, row_factory=dict_row) as db:
        with pytest.raises(ValueError):
            apply_recorded_migration(db, synthetic_migration("DEMO_escape", body))
        assert "DEMO_escape" not in applied_migrations(db)


def test_file_and_task_and_late_report_contracts_on_same_schema(db):

    from app.contracts.late_reports import LateReportInput

    from .test_conversation_threads_sql import owner
    from .test_library_lifecycle_sql import image, metadata, register
    from .test_regimen_successor_sql import _activate_initial
    from .test_today_care_sql import challenge, report, task, update

    pdf = metadata(db)
    assert register(db, pdf)["file"]["version"] == 1
    photo, _ = image(db, eligible=True)
    with owner(db, A):
        assert db.execute("select retire_personal_reference(%s)", (photo,)).fetchone()[0]["eligibility"] == "ineligible"
    row = task(db, reminder_minutes=30)
    completed = update(db, row, status="completed")
    assert completed.status == "completed" and completed.reminder_minutes == 30
    plan, _, _ = _activate_initial(db, A)
    rule = db.execute("select id from dose_rules where regimen_id=%s", (plan,)).fetchone()[0]
    occurrence = uuid4()
    db.execute(
        "insert into dose_occurrences(id,patient_id,regimen_id,rule_id,due_at,generation_key) "
        "values(%s,%s,%s,%s,clock_timestamp(),%s)",
        (occurrence, A, plan, rule, "DEMO:" + str(occurrence)),
    )
    values = LateReportInput(id=uuid4(), intake_status="reported_taken", reason="forgot_to_record")
    token = challenge(db, occurrence, plan, values)
    result = report(db, occurrence, values, token)
    assert result.intake_status == "reported_taken"
    with owner(db, A):
        assert (
            db.execute(
                "select intake_status from effective_dose_events where occurrence_id=%s", (occurrence,)
            ).fetchone()[0]
            == "reported_taken"
        )
    with owner(db, B):
        assert (
            db.execute("select count(*) from effective_dose_events where occurrence_id=%s", (occurrence,)).fetchone()[0]
            == 0
        )


def test_all_capabilities_http_and_worker_use_integrated_schema(db, integrated_dsn, monkeypatch, tmp_path):
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta

    import httpx
    from app.config import Settings
    from app.infrastructure.notification_jobs import PostgresNotificationJobs
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.transport.app_factory import create_app
    from app.transport.auth import AuthBoundary, StaticTokenVerifier
    from app.transport.container import build_supabase_container
    from fastapi.testclient import TestClient
    from psycopg.types.json import Jsonb

    from .test_release_a_schema030 import SqlWire
    from .test_today_care_sql import task

    now = datetime.now(UTC)
    row = task(db, due_at=(now + timedelta(hours=1)).isoformat(), reminder_minutes=30)
    subscription = uuid4()
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
    jobs = PostgresNotificationJobs(
        PostgresDatabase(dsn=integrated_dsn), patient_scope=A, include_late_reports=True, extended_tasks=True
    )
    jobs.sync_tasks(A, now)
    jobs.sync_tasks(A, now)
    assert db.execute("select count(*) from notification_deliveries where task_id=%s", (row.id,)).fetchone()[0] == 1
    assert jobs.claim(now) is None
    wire = SqlWire(db)
    transport = httpx.Client(transport=httpx.MockTransport(wire))

    def data_client(**kwargs):
        return SupabaseDataClient(**{**kwargs, "client": transport})

    monkeypatch.setattr("app.infrastructure.supabase_data.SupabaseDataClient", data_client)
    settings = replace(
        Settings.from_env(env_file=tmp_path / "absent.env"),
        persistence="supabase",
        auth_mode="supabase",
        supabase_url="https://demo.invalid",
        supabase_publishable_key="DEMO-publishable",
        model_provider="deterministic",
        vision_api_base_url=None,
        enable_medication_library_files=True,
        enable_care_task_followups=True,
        enable_late_dose_reports=True,
    )
    root = build_supabase_container(settings=settings)
    root.auth = AuthBoundary(
        mode="supabase", verifier=StaticTokenVerifier({"DEMO-A": {"sub": str(A)}, "DEMO-B": {"sub": str(B)}})
    )
    headers = {"Authorization": "Bearer DEMO-A"}
    medication = db.execute("select medication_id from medication_library_files limit 1").fetchone()[0]
    try:
        with TestClient(create_app(container=root, settings=settings)) as http:
            health = http.get("/api/health").json()
            assert all(
                health[key]
                for key in [
                    "medication_library_files_enabled",
                    "care_task_followups_enabled",
                    "late_dose_reports_enabled",
                ]
            )
            for path in [
                "/api/me/medications",
                "/api/me/regimens",
                "/api/me/today-attention",
                "/api/me/care-tasks",
                "/api/me/dose-follow-ups",
                "/api/reminders/alerts",
                "/api/evidence/gallery",
            ]:
                response = http.get(path, headers=headers)
                assert response.status_code == 200, (path, response.text)
            history = http.get("/api/me/medication-history?range_kind=7", headers=headers)
            assert history.status_code == 200, history.text
            assert any(item["reported_late"] for item in history.json()["entries"])
            files = http.get(f"/api/evidence/gallery/{medication}/files", headers=headers)
            assert files.status_code == 200 and files.json()["file_management_available"]
            assert any(item["format"] == "PDF" for item in files.json()["files"])
            foreign = http.get(f"/api/evidence/gallery/{medication}/files", headers={"Authorization": "Bearer DEMO-B"})
            assert foreign.status_code == 404
        assert {"effective_dose_events", "dose_report_entries", "medication_library_files"} <= {
            resource for _, resource in wire.calls
        }
    finally:
        transport.close()
