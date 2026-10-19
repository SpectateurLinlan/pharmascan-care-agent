"""Actual isolated PostgreSQL/RLS, with local Supabase auth/storage platform shims.

Never accepts a remote DSN. No production data is read or written.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("THREADS_TEST_DSN"), reason="isolated local PostgreSQL required")
A = UUID("d00d0000-0000-4000-8000-000000000001")
B = UUID("d00d0000-0000-4000-8000-000000000002")


def initialize_platform(c):
    """Local Supabase platform shims, not business-table or RLS substitutes."""
    c.execute("""
     CREATE SCHEMA auth; CREATE SCHEMA storage; CREATE SCHEMA extensions;
     CREATE TABLE auth.users(id uuid PRIMARY KEY);
     CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$
      SELECT nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
     GRANT USAGE ON SCHEMA auth TO authenticated,anon;
     GRANT EXECUTE ON FUNCTION auth.uid() TO authenticated,anon;
     CREATE TABLE storage.buckets(id text PRIMARY KEY,name text,public boolean DEFAULT false,
      file_size_limit bigint,allowed_mime_types text[]);
     CREATE TABLE storage.objects(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),bucket_id text,
      name text,owner uuid,metadata jsonb);
     ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;
     CREATE FUNCTION storage.foldername(text) RETURNS text[] LANGUAGE sql IMMUTABLE AS $$
      SELECT string_to_array($1,'/') $$;
    """)


@pytest.fixture(scope="module")
def db():
    import psycopg
    from psycopg import sql

    dsn = os.environ["THREADS_TEST_DSN"]
    assert urlparse(dsn).hostname == "127.0.0.1" and urlparse(dsn).port == 55439
    name = "mt_thread_test_" + uuid4().hex[:10]
    with psycopg.connect(dsn, autocommit=True) as admin:
        for role in ["authenticated", "anon", "service_role", "authenticator"]:
            if not admin.execute("select 1 from pg_roles where rolname=%s", (role,)).fetchone():
                admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    with psycopg.connect(f"postgresql://postgres@127.0.0.1:55439/{name}", autocommit=True) as c:
        initialize_platform(c)
        for path in sorted(Path("supabase/migrations").glob("*.sql")):
            try:
                c.execute(path.read_text(encoding="utf-8"))
            except Exception:
                print("ISOLATED_MIGRATION_FAILED", path.name)
                raise
        for owner in [A, B]:
            c.execute("insert into auth.users(id) values(%s)", (owner,))
            c.execute(
                "insert into public.patient_profiles(user_id,conversation_history_enabled) values(%s,true)", (owner,)
            )
        yield c


@contextmanager
def owner(c, patient):
    with c.transaction():
        c.execute("SET LOCAL ROLE authenticated")
        c.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(patient),))
        yield


def seeded(c, patient=A):
    conversation, session = uuid4(), uuid4()
    c.execute(
        (
            "insert into public.agent_sessions(id,patient_id,state,prompt_version,expires_at) "
            "values(%s,%s,'collecting','DEMO_threads_v1',now()+interval '2 hours')"
        ),
        (session, patient),
    )
    with owner(c, patient):
        c.execute("select public.create_conversation(%s,'DEMO conversation')", (conversation,))
        c.execute("update public.agent_sessions set conversation_id=%s where id=%s", (conversation, session))
    return conversation, session


def append(c, conversation, session, patient=A, text="DEMO answer"):
    from psycopg.types.json import Jsonb

    turn = uuid4()
    with owner(c, patient):
        assert (
            c.execute("select public.claim_conversation_turn(%s,%s,%s)", (conversation, turn, "a" * 64)).fetchone()[0]
            == "new"
        )
        c.execute(
            "select public.append_thread_turn(%s)",
            (
                Jsonb(
                    {
                        "id": str(turn),
                        "conversation_id": str(conversation),
                        "session_id": str(session),
                        "user_text": "DEMO question",
                        "assistant_text": text,
                        "photo_attached": True,
                    }
                ),
            ),
        )
    return turn


def test_empty_only_rollback_and_atomic_reapply(db):
    from psycopg import Rollback

    sql = Path("supabase/rollback/202610170026_empty_only.sql").read_text(encoding="utf-8")
    with db.transaction():
        db.execute(sql.replace("BEGIN;", "").replace("COMMIT;", ""))
        assert db.execute("select to_regclass('public.conversations')").fetchone()[0] is None
        raise Rollback()
    assert db.execute("select to_regclass('public.conversations')").fetchone()[0] is not None


def test_postgres_session_repository_preserves_real_thread_link(db):
    from app.infrastructure.postgres_db import PostgresDatabase
    from app.infrastructure.postgres_repos import build_postgres_repositories

    conversation, session = seeded(db)
    repositories = build_postgres_repositories(
        PostgresDatabase(dsn=f"postgresql://postgres@127.0.0.1:55439/{db.info.dbname}")
    )
    restored = repositories.sessions.get(A, session)
    assert restored and restored.conversation_id == conversation


def test_rls_claims_full_messages_and_idempotency(db):
    conversation, session = seeded(db)
    turn = append(db, conversation, session, text="合成测试" * 2000)
    with owner(db, A):
        assert db.execute(
            (
                "select length(full_assistant_text),length(assistant_text),photo_attached from "
                "public.conversation_turns where id=%s"
            ),
            (turn,),
        ).fetchone() == (8000, 4000, True)
        assert (
            db.execute("select public.claim_conversation_turn(%s,%s,%s)", (conversation, turn, "a" * 64)).fetchone()[0]
            == "completed"
        )
    with owner(db, B):
        assert db.execute("select count(*) from public.conversations where id=%s", (conversation,)).fetchone()[0] == 0
        assert db.execute("select count(*) from public.conversation_turns where id=%s", (turn,)).fetchone()[0] == 0
    with pytest.raises(__import__("psycopg").errors.RaiseException), owner(db, B):
        db.execute("select public.claim_conversation_turn(%s,%s,%s)", (conversation, uuid4(), "b" * 64))


def test_consent_and_session_binding(db):
    conversation, session = seeded(db, B)
    with owner(db, A), pytest.raises(__import__("psycopg").errors.ForeignKeyViolation):
        # Isolate the deliberate FK failure in a nested savepoint.
        with db.transaction():
            db.execute("update public.agent_sessions set conversation_id=%s where patient_id=%s", (conversation, A))
    db.execute("update public.patient_profiles set conversation_history_enabled=false where user_id=%s", (B,))
    with pytest.raises(__import__("psycopg").errors.RaiseException), owner(db, B):
        db.execute("select public.create_conversation(%s,'DEMO forbidden')", (uuid4(),))
    db.execute("update public.patient_profiles set conversation_history_enabled=true where user_id=%s", (B,))


def test_concurrent_duplicate_claim_and_anon_write_rejection(db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    import psycopg

    conversation, _ = seeded(db)
    identity = uuid4()
    barrier = Barrier(2)

    def claim():
        with psycopg.connect(f"postgresql://postgres@127.0.0.1:55439/{db.info.dbname}", autocommit=True) as c:
            barrier.wait(timeout=5)
            with owner(c, A):
                return c.execute(
                    "select public.claim_conversation_turn(%s,%s,%s)", (conversation, identity, "c" * 64)
                ).fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: claim(), range(2)))
    assert sorted(outcomes) == ["busy", "new"]
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("set local role anon")
        db.execute("select public.create_conversation(%s,'DEMO forbidden')", (uuid4(),))
    with pytest.raises(psycopg.errors.InsufficientPrivilege), owner(db, A):
        db.execute("insert into public.conversations(id,patient_id,title) values(%s,%s,'DEMO bypass')", (uuid4(), A))


def test_old_append_retention_does_not_delete_thread_and_clear_is_owned(db):
    from psycopg.types.json import Jsonb

    conversation, session = seeded(db)
    turn = append(db, conversation, session)
    db.execute("update public.conversation_turns set created_at=now()-interval '40 days' where id=%s", (turn,))
    with owner(db, A):
        for _ in range(201):
            db.execute(
                "select public.append_conversation_turn(%s)",
                (
                    Jsonb(
                        {
                            "id": str(uuid4()),
                            "patient_id": str(A),
                            "session_id": str(session),
                            "user_text": "DEMO legacy",
                            "assistant_text": "DEMO legacy answer",
                        }
                    ),
                ),
            )
        assert db.execute("select count(*) from public.conversation_turns where id=%s", (turn,)).fetchone()[0] == 1
        assert (
            db.execute("select count(*) from public.conversation_turns where conversation_id is null").fetchone()[0]
            == 200
        )
        db.execute("select public.clear_conversation_history()")
        assert db.execute("select count(*) from public.conversations").fetchone()[0] == 0
    with owner(db, B):
        assert db.execute("select count(*) from public.conversations").fetchone()[0] > 0
