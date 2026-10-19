"""Actual SQL proof against observed hosted grants, without production writes."""

import os
from pathlib import Path

import pytest

from .test_conversation_threads_sql import A, owner, seeded
from .test_conversation_threads_sql import db as db

pytestmark = pytest.mark.skipif(not os.environ.get("THREADS_TEST_DSN"), reason="isolated local PostgreSQL required")


def test_029_removes_dangerous_defaults_preserves_patient_crud_and_rpc(db):
    from datetime import UTC, datetime
    from uuid import uuid4

    import psycopg
    from app.contracts.medication_evidence import MedicationImage
    from psycopg.types.json import Jsonb

    from .test_draft_deletion_sql import seed

    seeded(db)
    migration = Path("supabase/migrations/202610180029_patient_table_privileges.sql").read_text(encoding="utf-8")
    # Reproduce captured hosted-platform defaults, not relaxed medical guards.
    db.execute("GRANT TRUNCATE,REFERENCES,TRIGGER ON patient_medications TO authenticated")
    modern = int(db.execute("SHOW server_version_num").fetchone()[0]) >= 170000
    if modern:
        db.execute("GRANT MAINTAIN ON patient_medications TO authenticated")
    db.execute("GRANT ALL ON conversation_turns TO anon")
    db.execute("GRANT UPDATE,DELETE ON image_embeddings,medication_images TO authenticated")
    db.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon,authenticated")
    before = db.execute("SELECT count(*) FROM agent_sessions").fetchone()[0]
    crud = db.execute("SELECT has_table_privilege('authenticated','patient_medications','SELECT')").fetchone()[0]
    rpc = db.execute(
        "SELECT has_function_privilege('authenticated','create_conversation(uuid,text)','EXECUTE')"
    ).fetchone()[0]
    db.execute(migration)
    db.execute(migration)  # Privilege tightening is safely retryable.
    if modern:
        assert not db.execute(
            "SELECT has_table_privilege('authenticated','patient_medications','MAINTAIN')"
        ).fetchone()[0]
    with owner(db, A), pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("TRUNCATE patient_medications CASCADE")
    for privilege in ["TRUNCATE", "REFERENCES", "TRIGGER"]:
        assert not db.execute(
            "SELECT has_table_privilege(%s,%s,%s)", ("authenticated", "patient_medications", privilege)
        ).fetchone()[0]
    for privilege in ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"]:
        assert not db.execute(
            "SELECT has_table_privilege(%s,%s,%s)", ("anon", "conversation_turns", privilege)
        ).fetchone()[0]
    assert (
        db.execute("SELECT has_table_privilege('authenticated','patient_medications','SELECT')").fetchone()[0] == crud
    )
    assert (
        db.execute(
            "SELECT has_function_privilege('authenticated','create_conversation(uuid,text)','EXECUTE')"
        ).fetchone()[0]
        == rpc
    )
    assert not db.execute("SELECT has_table_privilege('authenticated','image_embeddings','UPDATE')").fetchone()[0]
    assert not db.execute("SELECT has_table_privilege('authenticated','medication_images','UPDATE')").fetchone()[0]
    assert db.execute("SELECT has_column_privilege('authenticated','medication_images','data','UPDATE')").fetchone()[0]
    with owner(db, A):
        row = db.execute("SELECT create_conversation(gen_random_uuid(),'DEMO after privilege tightening')").fetchone()
        assert row is not None
    _, medication, _ = seed(db)
    photo = MedicationImage(
        id=uuid4(),
        patient_id=A,
        medication_id=medication,
        image_kind="loose_pill",
        storage_path=f"{A}/DEMO.png",
        checksum="a" * 64,
        source_description="DEMO only",
        eligibility_reason="reference_photo_associated_only",
        created_at=datetime.now(UTC),
    )
    with owner(db, A):
        db.execute(
            "INSERT INTO medication_images(id,patient_id,medication_id,data) VALUES(%s,%s,%s,%s)",
            (photo.id, A, medication, Jsonb(photo.model_dump(mode="json"))),
        )
        retired = db.execute("SELECT retire_personal_reference(%s)", (photo.id,)).fetchone()[0]
        assert retired["eligibility"] == "ineligible"
    db.execute("CREATE TABLE public.release_acl_probe(patient_id uuid)")
    assert not db.execute("SELECT has_table_privilege('anon','release_acl_probe','SELECT')").fetchone()[0]
    assert not db.execute("SELECT has_table_privilege('authenticated','release_acl_probe','TRUNCATE')").fetchone()[0]
    assert not db.execute("SELECT has_table_privilege('authenticated','release_acl_probe','SELECT')").fetchone()[0]
    assert db.execute("SELECT count(*) FROM agent_sessions").fetchone()[0] == before
