"""Actual 026 -> 027 -> 028 upgrade over existing synthetic rows; local only."""

import os
from pathlib import Path
from uuid import uuid4

import pytest

from .test_conversation_threads_sql import A, initialize_platform, seeded
from .test_conversation_threads_sql import db as db
from .test_draft_deletion_sql import delete, seed

pytestmark = pytest.mark.skipif(not os.environ.get("THREADS_TEST_DSN"), reason="isolated local PostgreSQL required")


def test_ledger_inspection_is_really_read_only_with_or_without_existing_ledger(db):
    from app.infrastructure.postgres_db import PostgresDatabase
    from app.infrastructure.postgres_migrations import applied_migrations, ensure_ledger

    with PostgresDatabase(dsn=db.info.dsn).connect() as c:
        c.execute("SET TRANSACTION READ ONLY")
        assert applied_migrations(c) == {}
        assert c.execute("SELECT to_regclass('public.core_schema_migrations') AS name").fetchone()["name"] is None
    with PostgresDatabase(dsn=db.info.dsn).connect() as c:
        ensure_ledger(c)
        c.execute("INSERT INTO core_schema_migrations(version,sha256,name) VALUES('DEMO','synthetic','DEMO')")
        c.commit()
    with PostgresDatabase(dsn=db.info.dsn).connect() as c:
        c.execute("SET TRANSACTION READ ONLY")
        assert applied_migrations(c) == {"DEMO": "synthetic"}


def test_existing_026_data_survives_upgrade_and_new_delete_contract_works(db):
    import psycopg
    from psycopg import sql

    name = "mt_release_upgrade_" + uuid4().hex[:8]
    db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    with psycopg.connect(f"postgresql://postgres@127.0.0.1:55439/{name}", autocommit=True) as c:
        initialize_platform(c)
        migrations = sorted(Path("supabase/migrations").glob("*.sql"))
        for migration in migrations:
            if migration.name[:12] <= "202610170026":
                c.execute(migration.read_text(encoding="utf-8"))
        c.execute("insert into auth.users(id) values(%s)", (A,))
        c.execute("insert into patient_profiles(user_id,conversation_history_enabled) values(%s,true)", (A,))
        source, medication, plan = seed(c)
        conversation, session = seeded(c)
        before = c.execute("select to_jsonb(r) from regimen_versions r where id=%s", (plan,)).fetchone()[0]
        assert (
            c.execute("select to_regprocedure('delete_unconfirmed_medication(text,uuid,boolean)')").fetchone()[0]
            is None
        )
        for migration in migrations:
            if migration.name[:12] > "202610170026":
                c.execute(migration.read_text(encoding="utf-8"))
        after = c.execute(
            "select to_jsonb(r)-'patient_edited' from regimen_versions r where id=%s", (plan,)
        ).fetchone()[0]
        assert before == after
        assert (
            c.execute("select conversation_id from agent_sessions where id=%s", (session,)).fetchone()[0]
            == conversation
        )
        assert c.execute('select core_trace_summary_is_safe(\'{"error_code":"REGIMEN_OVERLAP"}\')').fetchone()[0]
        assert delete(c, plan)["deleted"]
        assert c.execute("select count(*) from patient_medications where id=%s", (medication,)).fetchone()[0] == 0
        assert c.execute("select count(*) from source_documents where id=%s", (source,)).fetchone()[0] == 0
