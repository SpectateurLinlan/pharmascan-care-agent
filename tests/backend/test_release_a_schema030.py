"""Real schema001-030 and RLS through FastAPI; synthetic Auth and PostgREST wire bridge.

Not a hosted Supabase/Auth/Storage test. No environment business credentials are loaded.
"""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from .test_conversation_threads_sql import A, B, initialize_platform, owner
from .test_regimen_successor_sql import _activate_initial

pytestmark = pytest.mark.skipif(not os.environ.get("THREADS_TEST_DSN"), reason="isolated PostgreSQL required")


@pytest.fixture(scope="module")
def schema030():
    dsn = os.environ["THREADS_TEST_DSN"]
    assert urlparse(dsn).hostname == "127.0.0.1" and urlparse(dsn).port == 55441
    name = "mt_rc030_" + uuid4().hex[:10]
    with psycopg.connect(dsn, autocommit=True) as admin:
        for role in ["authenticated", "anon", "service_role", "authenticator"]:
            if not admin.execute("select 1 from pg_roles where rolname=%s", (role,)).fetchone():
                admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        with psycopg.connect(f"postgresql://postgres@127.0.0.1:55441/{name}", autocommit=True) as db:
            initialize_platform(db)
            for path in sorted(Path("supabase/migrations").glob("*.sql")):
                if path.name[:12] <= "202610190030":
                    db.execute(path.read_text("utf-8"))
            for patient in [A, B]:
                db.execute("insert into auth.users(id) values(%s)", (patient,))
                db.execute("insert into patient_profiles(user_id,reminders_enabled) values(%s,true)", (patient,))
            yield db
    finally:
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def split_terms(value):
    terms, start, depth = [], 0, 0
    for i, char in enumerate(value):
        depth += (char == "(") - (char == ")")
        if char == "," and depth == 0:
            terms.append(value[start:i])
            start = i + 1
    return terms + [value[start:]]


def test_032_sql_can_upgrade_030_without_file_or_late_report_objects(schema030):
    """SQL independence is real; the chronological release runner still refuses the gap."""
    db = schema030
    with db.transaction():
        assert db.execute(
            "select to_regclass('medication_library_files'),to_regclass('dose_report_entries')"
        ).fetchone() == (None, None)
        migration = Path("supabase/migrations/202610190032_care_task_followup_ux.sql").read_text("utf-8")
        db.execute(migration.replace("BEGIN;", "").replace("COMMIT;", ""))
        now = datetime.now(UTC)
        values = {
            "id": str(uuid4()),
            "title": "DEMO independent032",
            "category": "medication_review",
            "due_at": (now + timedelta(days=1)).isoformat(),
            "reminder_minutes": 30,
            "historical_entry": False,
            "source": "patient_reported",
            "notes": "DEMO synthetic",
        }
        with owner(db, A):
            result = db.execute("select create_medication_care_task(%s)", (Jsonb(values),)).fetchone()[0]
        assert result["reminder_minutes"] == 30 and result["history"][0]["title"] == values["title"]
        with owner(db, B):
            assert (
                db.execute("select count(*) from medication_care_tasks where id=%s", (result["id"],)).fetchone()[0] == 0
            )
        raise psycopg.Rollback()


def condition(value, args):
    for operator in ["and", "or"]:
        if value.startswith(operator + "("):
            return (
                sql.SQL("(")
                + sql.SQL(" " + operator + " ").join(
                    condition(term, args) for term in split_terms(value[len(operator) + 1 : -1])
                )
                + sql.SQL(")")
            )
    column, op, operand = value.split(".", 2)
    column = sql.Identifier(column)
    if op == "is":
        assert operand == "null"
        return column + sql.SQL(" IS NULL")
    if op == "in":
        values = operand[1:-1].split(",")
        args.extend(values)
        return column + sql.SQL(" IN (") + sql.SQL(",").join(sql.Placeholder() for _ in values) + sql.SQL(")")
    operators = {"eq": "=", "neq": "<>", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
    args.append(operand)
    return column + sql.SQL(" " + operators[op] + " %s")


class SqlWire:
    """Strict small test-only wire translator. SQL results and role enforcement are real."""

    def __init__(self, db):
        self.db, self.calls = db, []

    def __call__(self, request):
        resource = request.url.path.removeprefix("/rest/v1/")
        self.calls.append((request.method, resource))
        patient = A if request.headers["authorization"] == "Bearer DEMO-A" else B
        with owner(self.db, patient):
            if resource.startswith("rpc/"):
                args = json.loads(request.content)
                result = self.db.execute(
                    sql.SQL("SELECT {}({})").format(
                        sql.Identifier(resource.split("/")[1]),
                        sql.SQL(",").join(sql.Identifier(k) + sql.SQL(" => %s") for k in args),
                    ),
                    [Jsonb(v) if isinstance(v, (dict, list)) else v for v in args.values()],
                ).fetchone()[0]
                return httpx.Response(200, content=json.dumps(result, default=str))
            assert request.method in {"GET", "POST"}, (request.method, resource)
            if request.method == "POST":
                body = json.loads(request.content)
                self.db.execute(
                    sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING").format(
                        sql.Identifier(resource),
                        sql.SQL(",").join(map(sql.Identifier, body)),
                        sql.SQL(",").join(sql.Placeholder() for _ in body),
                    ),
                    [Jsonb(v) if isinstance(v, (dict, list)) else v for v in body.values()],
                )
                return httpx.Response(201, json=[])
            params, args, clauses = dict(request.url.params), [], []
            for key, value in params.items():
                if key in {"select", "order", "limit", "offset"}:
                    continue
                expression = key + value if key in {"and", "or"} else key + "." + value
                clauses.append(condition(expression, args))
            selection = params.get("select", "*")
            columns = sql.SQL("*") if selection == "*" else sql.SQL(",").join(map(sql.Identifier, selection.split(",")))
            query = sql.SQL("SELECT {} FROM {}").format(columns, sql.Identifier(resource))
            if clauses:
                query += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses)
            if "order" in params:
                ordering = []
                for term in params["order"].split(","):
                    parts = term.split(".")
                    direction = parts[1] if len(parts) > 1 else "asc"
                    assert direction in {"asc", "desc"}
                    ordering.append(sql.Identifier(parts[0]) + sql.SQL(" " + direction))
                query += sql.SQL(" ORDER BY ") + sql.SQL(",").join(ordering)
            cursor = self.db.execute(query, args)
            fields = [field.name for field in cursor.description]
            rows = [dict(zip(fields, row, strict=True)) for row in cursor.fetchall()]
            total = len(rows)
            offset = int(params.get("offset", 0))
            rows = rows[offset : offset + int(params.get("limit", total))]
            return httpx.Response(200, content=json.dumps(rows, default=str), headers={"Content-Range": f"*/{total}"})


def test_schema030_public_routes_with_real_records_and_owner_rls(schema030, monkeypatch, tmp_path):
    from dataclasses import replace

    from app.config import Settings
    from app.contracts.medication_evidence import MedicationImage
    from app.infrastructure.supabase_data import SupabaseDataClient
    from app.transport.app_factory import create_app
    from app.transport.auth import AuthBoundary, StaticTokenVerifier
    from app.transport.container import build_supabase_container
    from fastapi.testclient import TestClient

    db = schema030
    plan, medication, _ = _activate_initial(db, A)
    ended, _, _ = _activate_initial(db, A)
    db.execute("update regimen_versions set state='ended',effective_to=clock_timestamp() where id=%s", (ended,))
    _activate_initial(db, B)
    now = datetime.now(UTC)
    occurrence = uuid4()
    rule = db.execute("select id from dose_rules where patient_id=%s and regimen_id=%s", (A, plan)).fetchone()[0]
    db.execute(
        "insert into dose_occurrences(id,patient_id,regimen_id,rule_id,due_at,generation_key) "
        "values(%s,%s,%s,%s,%s,%s)",
        (occurrence, A, plan, rule, now + timedelta(seconds=5), "DEMO:" + str(occurrence)),
    )

    class Clock:
        def now(self):
            return now + timedelta(minutes=1)

    photo = MedicationImage(
        id=uuid4(),
        patient_id=A,
        medication_id=medication,
        image_kind="package",
        storage_path=f"{A}/DEMO.png",
        checksum="a" * 64,
        source_description="DEMO synthetic packaging",
        eligibility_reason="image_content_not_independently_validated_comparison_disabled",
        created_at=now,
    )
    db.execute(
        "insert into medication_images(id,patient_id,medication_id,data) values(%s,%s,%s,%s)",
        (photo.id, A, medication, Jsonb(photo.model_dump(mode="json"))),
    )
    wire = SqlWire(db)
    transport_client = httpx.Client(transport=httpx.MockTransport(wire))

    def database_client(**kwargs):
        return SupabaseDataClient(**{**kwargs, "client": transport_client})

    monkeypatch.setattr("app.infrastructure.supabase_data.SupabaseDataClient", database_client)
    settings = replace(
        Settings.from_env(env_file=tmp_path / "absent.env"),
        persistence="supabase",
        auth_mode="supabase",
        supabase_url="https://demo.invalid",
        supabase_publishable_key="DEMO-publishable",
        model_provider="deterministic",
        vision_api_base_url=None,
        enable_medication_library_files=False,
        enable_late_dose_reports=False,
        enable_care_task_followups=False,
    )
    root = build_supabase_container(settings=settings, clock=Clock())
    root.auth = AuthBoundary(
        mode="supabase", verifier=StaticTokenVerifier({"DEMO-A": {"sub": str(A)}, "DEMO-B": {"sub": str(B)}})
    )
    headers = {"Authorization": "Bearer DEMO-A"}
    try:
        with TestClient(create_app(container=root, settings=settings)) as http:
            health = http.get("/api/health").json()
            assert all(
                health[key] is False
                for key in [
                    "medication_library_files_enabled",
                    "late_dose_reports_enabled",
                    "care_task_followups_enabled",
                ]
            )
            medications = http.get("/api/me/medications", headers=headers)
            assert medications.status_code == 200 and medications.json()["item_count"] == 1
            assert medications.json()["medications"][0]["regimen_id"] == str(plan)
            for path in [
                "/api/me/regimens",
                "/api/evidence/gallery",
                "/api/reminders/alerts",
                f"/api/doses/due?regimen_id={plan}",
                "/api/me/medication-history?range_kind=7",
                f"/api/me/dose-history?regimen_id={plan}",
                "/api/me/care-tasks",
            ]:
                response = http.get(path, headers=headers)
                assert response.status_code == 200, (path, response.text)
            regimens = http.get("/api/me/regimens", headers=headers).json()
            assert {row["state"] for row in regimens} == {"active", "ended"}
            history = http.get("/api/me/medication-history?range_kind=7", headers=headers).json()
            assert any(row["id"] == f"scheduled:{occurrence}" and not row["reported"] for row in history["entries"])
            alerts = http.get("/api/reminders/alerts", headers=headers).json()
            assert any(row["occurrence_id"] == str(occurrence) for row in alerts)
            gallery = http.get("/api/evidence/gallery", headers=headers).json()
            assert any(
                row["images"] and row["images"][0]["id"] == str(photo.id) and row["eligible_count"] == 0
                for row in gallery
            )
            values = {
                "id": str(uuid4()),
                "title": "DEMO legacy task",
                "category": "medication_review",
                "due_at": (now + timedelta(hours=2)).isoformat(),
                "confirmed": True,
                "reminder_minutes": 0,
            }
            task = http.post("/api/me/care-tasks", headers=headers, json=values)
            assert task.status_code == 200, task.text
            assert len(http.get("/api/me/care-tasks", headers=headers).json()) == 1
            assert http.get("/api/me/care-tasks", headers={"Authorization": "Bearer DEMO-B"}).json() == []
            task_id = task.json()["id"]
            files = http.get(f"/api/evidence/gallery/{medication}/files", headers=headers)
            assert files.status_code == 200 and files.json()["file_management_available"] is False
            assert files.json()["files"] and files.json()["files"][0]["image_id"] == str(photo.id)
            assert http.get("/api/me/dose-follow-ups", headers=headers).status_code == 503
            assert http.get("/api/me/medications").status_code == 401
        forbidden = {"medication_library_files", "dose_report_entries", "effective_dose_events"}
        assert not {resource for _, resource in wire.calls} & forbidden
        assert db.execute(
            "select to_regclass('medication_library_files'),to_regclass('dose_report_entries'),"
            "to_regclass('effective_dose_events')"
        ).fetchone() == (None, None, None)
        from app.infrastructure.notification_jobs import PostgresNotificationJobs
        from app.infrastructure.postgres_db import PostgresDatabase

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
        jobs = PostgresNotificationJobs(
            PostgresDatabase(dsn=f"postgresql://postgres@127.0.0.1:55441/{db.info.dbname}"), patient_scope=A
        )
        jobs.sync_tasks(A, now)
        jobs.sync_tasks(A, now)
        queued = db.execute("select remind_at from notification_deliveries where task_id=%s", (task_id,)).fetchall()
        assert len(queued) == 1 and queued[0][0] == datetime.fromisoformat(values["due_at"])
        assert jobs.claim(now) is None  # Future reminder must not be dispatched early.
    finally:
        transport_client.close()
