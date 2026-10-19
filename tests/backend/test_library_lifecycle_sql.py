"""Real localhost PostgreSQL 17 SQL/RLS; auth/storage schemas are platform shims."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from .test_conversation_threads_sql import A, B, initialize_platform, owner
from .test_draft_deletion_sql import seed

pytestmark = pytest.mark.skipif(not os.environ.get("THREADS_TEST_DSN"), reason="isolated localhost PostgreSQL required")
UP = Path("supabase/migrations/202610190031_medication_library_file_lifecycle.sql")
DOWN = Path("supabase/rollback/202610190031_medication_library_file_lifecycle_down.sql")


@pytest.fixture(scope="module")
def db():
    dsn = os.environ["THREADS_TEST_DSN"]
    assert urlparse(dsn).hostname == "127.0.0.1" and urlparse(dsn).port == 55441
    name = "mt_library_test_" + uuid4().hex[:10]
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as admin:
        for role in ["authenticated", "anon", "service_role", "authenticator"]:
            if not admin.execute("select 1 from pg_roles where rolname=%s", (role,)).fetchone():
                admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    with psycopg.connect(
        f"postgresql://postgres@127.0.0.1:55441/{name}", autocommit=True, connect_timeout=5
    ) as connection:
        initialize_platform(connection)
        for path in sorted(Path("supabase/migrations").glob("*.sql")):
            if path.name < UP.name:
                connection.execute(path.read_text(encoding="utf-8"))
        # Model the previously observed Supabase function default ACL.
        connection.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO service_role")
        connection.execute(UP.read_text(encoding="utf-8"))
        for patient in [A, B]:
            connection.execute("insert into auth.users(id) values(%s)", (patient,))
            connection.execute("insert into patient_profiles(user_id) values(%s)", (patient,))
        yield connection
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def metadata(db, patient=A, **changes):
    if patient == A:
        _, medication, _ = seed(db)
    else:
        medication = uuid4()
        db.execute(
            "insert into patient_medications(id,patient_id,display_name) values(%s,%s,'DEMO B')", (medication, B)
        )
    checksum = uuid4().hex * 2
    value = dict(
        id=str(uuid4()),
        patient_id=str(patient),
        medication_id=str(medication),
        storage_path=f"{patient}/library/{medication}/{checksum}.pdf",
        checksum=checksum,
        original_filename="DEMO.pdf",
        display_title="DEMO original",
        category="prescription",
        content_type="application/pdf",
        byte_size=100,
        description="Synthetic SQL test",
    )
    return value | changes


def register(db, value, patient=A):
    with owner(db, patient):
        return db.execute("select register_medication_library_pdf(%s)", (Jsonb(value),)).fetchone()[0]


def image(db, *, eligible=False, source=False):
    source_id, medication, _ = seed(db)
    identifier = uuid4()
    data = dict(
        id=str(identifier),
        patient_id=str(A),
        medication_id=str(medication),
        image_kind="loose_pill",
        storage_path=f"{A}/DEMO-{identifier}.png",
        checksum=uuid4().hex * 2,
        source_description="DEMO only",
        eligibility="eligible" if eligible else "reference_only",
        eligibility_reason="DEMO_legacy",
        created_at=datetime.now(UTC).isoformat(),
    )
    db.execute(
        "insert into medication_images(id,patient_id,medication_id,source_id,data) values(%s,%s,%s,%s,%s)",
        (identifier, A, medication, source_id if source else None, Jsonb(data)),
    )
    return identifier, data


def manage(db, identifier, action, version=1, patient=A, **values):
    with owner(db, patient):
        return db.execute(
            "select manage_personal_gallery_image(%s,%s,%s,%s,%s,%s)",
            (
                identifier,
                action,
                version,
                values.get("image_kind"),
                values.get("description"),
                values.get("confirmed", True),
            ),
        ).fetchone()[0]


def test_up_empty_rollback_reapply_and_repeat_application(db):
    db.execute(DOWN.read_text(encoding="utf-8"))
    assert db.execute("select to_regclass('medication_library_files')").fetchone()[0] is None
    db.execute(UP.read_text(encoding="utf-8"))
    with pytest.raises(psycopg.errors.DuplicateTable):
        db.execute(UP.read_text(encoding="utf-8"))
    db.execute("ROLLBACK")
    assert db.execute("select to_regclass('medication_library_files')").fetchone()[0]


def test_rpc_acl_and_no_direct_writes(db):
    signatures = [
        "register_medication_library_pdf(jsonb)",
        "update_medication_library_pdf(uuid,integer,text,text,text)",
        "tombstone_medication_library_pdf(uuid,boolean)",
        "ack_medication_library_pdf_cleanup(uuid)",
        "manage_personal_gallery_image(uuid,text,integer,text,text,boolean)",
        "ack_personal_gallery_image_cleanup(uuid)",
        "retire_personal_reference(uuid)",
    ]
    for signature in signatures:
        assert db.execute("select has_function_privilege('authenticated',%s,'EXECUTE')", (signature,)).fetchone()[0]
        for role in ["anon", "service_role"]:
            assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (role, signature)).fetchone()[0]
    for table in ["medication_library_files", "medication_library_file_audit", "medication_image_audit"]:
        for privilege in ["INSERT", "UPDATE", "DELETE", "TRUNCATE"]:
            assert not db.execute("select has_table_privilege('authenticated',%s,%s)", (table, privilege)).fetchone()[0]


def test_registration_idempotency_audit_and_cross_patient_rls(db):
    value = metadata(db)
    first = register(db, value)
    assert not first["duplicate"] and register(db, value)["duplicate"]
    with owner(db, B):
        assert not db.execute("select id from medication_library_files where id=%s", (value["id"],)).fetchall()
        assert not db.execute(
            "select id from medication_library_file_audit where file_id=%s", (value["id"],)
        ).fetchall()
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        register(db, value, B)
    assert (
        db.execute("select count(*) from medication_library_file_audit where file_id=%s", (value["id"],)).fetchone()[0]
        == 1
    )


@pytest.mark.parametrize(
    "change", [{"checksum": "bad"}, {"storage_path": "../DEMO.pdf"}, {"byte_size": 0}, {"category": "invalid"}]
)
def test_invalid_metadata_cannot_persist(db, change):
    value = metadata(db, **change)
    with pytest.raises(psycopg.Error):
        register(db, value)
    assert not db.execute("select id from medication_library_files where id=%s", (value["id"],)).fetchall()


def test_foreign_patient_medication_rejected_and_same_bytes_allowed_per_patient(db):
    value = metadata(db)
    register(db, value)
    other = metadata(db, B, checksum=value["checksum"])
    register(db, other, B)
    value = metadata(db, medication_id=other["medication_id"])
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        register(db, value)


def test_concurrent_registration_is_one_row_and_one_audit(db):
    value = metadata(db)

    def submit(_):
        with psycopg.connect(
            f"postgresql://postgres@127.0.0.1:55441/{db.info.dbname}", autocommit=True, connect_timeout=5
        ) as connection:
            return register(connection, value)["duplicate"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(8)))
    assert results.count(False) == 1 and results.count(True) == 7
    assert (
        db.execute("select count(*) from medication_library_file_audit where file_id=%s", (value["id"],)).fetchone()[0]
        == 1
    )


@pytest.mark.parametrize("expected", [0, None])
def test_pdf_stale_or_missing_version_rejected(db, expected):
    value = metadata(db)
    register(db, value)
    with pytest.raises(psycopg.Error), owner(db, A):
        db.execute("select update_medication_library_pdf(%s,%s,'DEMO edit','other','')", (value["id"], expected))


def test_pdf_edit_delete_retry_cleanup_and_protected_source(db):
    value = metadata(db)
    register(db, value)
    with owner(db, A):
        row = db.execute(
            "select to_jsonb(update_medication_library_pdf(%s,1,'DEMO edit','other',''))", (value["id"],)
        ).fetchone()[0]
        assert row["version"] == 2
        result = db.execute("select tombstone_medication_library_pdf(%s,true)", (value["id"],)).fetchone()[0]
        assert result["cleanup_pending"]
        assert db.execute("select tombstone_medication_library_pdf(%s,true)", (value["id"],)).fetchone()[0] == result
        db.execute("select ack_medication_library_pdf_cleanup(%s)", (value["id"],))
    assert not db.execute(
        "select cleanup_pending from medication_library_files where id=%s", (value["id"],)
    ).fetchone()[0]
    source, _, _ = seed(db)
    protected = metadata(db)
    register(db, protected)
    db.execute("update medication_library_files set source_document_id=%s where id=%s", (source, protected["id"]))
    with pytest.raises(psycopg.Error), owner(db, A):
        db.execute("select tombstone_medication_library_pdf(%s,true)", (protected["id"],))


def test_retire_eligible_photo_is_audited_and_not_deleted(db):
    identifier, _ = image(db, eligible=True)
    with owner(db, A):
        result = db.execute("select retire_personal_reference(%s)", (identifier,)).fetchone()[0]
        assert result["eligibility"] == "ineligible"
    assert (
        db.execute("select action from medication_image_audit where image_id=%s", (identifier,)).fetchone()[0]
        == "stopped_comparison"
    )
    assert db.execute("select id from medication_images where id=%s", (identifier,)).fetchone()


def test_photo_edit_remove_delete_scope_and_cleanup(db):
    identifier, _ = image(db)
    with pytest.raises(psycopg.Error):
        manage(db, identifier, "edit", patient=B, image_kind="package", description="DEMO")
    edited = manage(db, identifier, "edit", image_kind="package", description="DEMO")
    assert edited["image"]["eligibility"] == "ineligible"
    assert edited["image"]["metadata_version"] == 2
    removed = manage(db, identifier, "remove", version=2)
    assert removed["image"]["gallery_removed"]
    deleted = manage(db, identifier, "delete", version=3)
    assert deleted["cleanup_pending"] and deleted["image"]["deleted_at"]
    assert manage(db, identifier, "delete", version=3) == deleted
    with owner(db, A):
        db.execute("select ack_personal_gallery_image_cleanup(%s)", (identifier,))
    assert not db.execute(
        "select (data->>'cleanup_pending')::boolean from medication_images where id=%s", (identifier,)
    ).fetchone()[0]


def test_source_photo_deletion_is_rejected(db):
    identifier, _ = image(db, source=True)
    with pytest.raises(psycopg.Error):
        manage(db, identifier, "delete")


def test_null_photo_action_is_rejected_without_an_audit_or_evidence_mutation(db):
    identifier, data = image(db)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        manage(db, identifier, None)
    assert db.execute("select data from medication_images where id=%s", (identifier,)).fetchone()[0] == data
    assert not db.execute("select id from medication_image_audit where image_id=%s", (identifier,)).fetchone()


def embedding(db, identifier, data):
    from app.contracts.medication_evidence import ImageEmbedding, VisualReferenceSet

    from .test_medication_evidence import Vision

    reference = VisualReferenceSet(
        id=uuid4(), patient_id=A, medication_id=data["medication_id"], model=Vision.model, created_at=datetime.now(UTC)
    )
    row = ImageEmbedding(
        id=uuid4(),
        patient_id=A,
        medication_id=data["medication_id"],
        image_id=identifier,
        reference_set_id=reference.id,
        result=Vision().encode(b"DEMO")[1],
    )
    db.execute(
        "insert into visual_reference_sets(id,patient_id,medication_id,data) values(%s,%s,%s,%s)",
        (reference.id, A, reference.medication_id, Jsonb(reference.model_dump(mode="json"))),
    )
    db.execute(
        "insert into image_embeddings(id,patient_id,medication_id,image_id,reference_set_id,data) "
        "values(%s,%s,%s,%s,%s,%s)",
        (row.id, A, row.medication_id, identifier, reference.id, Jsonb(row.model_dump(mode="json"))),
    )
    return row.id, reference.id


@pytest.mark.parametrize("operation", ["retire", "edit", "remove", "delete"])
def test_embedding_retirement_preserves_reference_set_and_evidence(db, operation):
    identifier, data = image(db, eligible=True)
    embed_id, reference_id = embedding(db, identifier, data)
    if operation == "retire":
        with owner(db, A):
            db.execute("select retire_personal_reference(%s)", (identifier,))
    else:
        manage(db, identifier, operation, image_kind="package", description="DEMO changed")
    assert not db.execute("select id from image_embeddings where id=%s", (embed_id,)).fetchone()
    assert db.execute("select id from medication_images where id=%s", (identifier,)).fetchone()
    assert db.execute("select id from visual_reference_sets where id=%s", (reference_id,)).fetchone()


def test_shared_storage_path_blocks_photo_deletion(db):
    identifier, data = image(db)
    _, other_medication, _ = seed(db)
    shared = data | {"id": str(uuid4()), "medication_id": str(other_medication), "checksum": uuid4().hex * 2}
    db.execute(
        "insert into medication_images(id,patient_id,medication_id,data) values(%s,%s,%s,%s)",
        (shared["id"], A, other_medication, Jsonb(shared)),
    )
    with pytest.raises(psycopg.Error):
        manage(db, identifier, "delete")
    assert not db.execute("select data->>'deleted_at' from medication_images where id=%s", (identifier,)).fetchone()[0]


def test_new_reference_cannot_race_with_a_committing_photo_tombstone(db):
    from threading import Event

    identifier, data = image(db)
    _, other_medication, _ = seed(db)
    shared = data | {"id": str(uuid4()), "medication_id": str(other_medication), "checksum": uuid4().hex * 2}
    started = Event()

    def attach():
        with psycopg.connect(
            f"postgresql://postgres@127.0.0.1:55441/{db.info.dbname}", autocommit=True, connect_timeout=5
        ) as connection:
            started.set()
            try:
                with owner(connection, A):
                    connection.execute(
                        "insert into medication_images(id,patient_id,medication_id,data) values(%s,%s,%s,%s)",
                        (shared["id"], A, other_medication, Jsonb(shared)),
                    )
            except psycopg.Error as error:
                return error.sqlstate
            return "inserted"

    with ThreadPoolExecutor(max_workers=1) as pool:
        with owner(db, A):
            db.execute("select manage_personal_gallery_image(%s,'delete',1,null,null,true)", (identifier,))
            future = pool.submit(attach)
            assert started.wait(5)
        assert future.result(timeout=5) == "P7502"
    assert not db.execute("select id from medication_images where id=%s", (shared["id"],)).fetchone()


def test_concurrent_metadata_edits_enforce_one_version_and_one_audit(db):
    value = metadata(db)
    register(db, value)

    def submit(number):
        with psycopg.connect(
            f"postgresql://postgres@127.0.0.1:55441/{db.info.dbname}", autocommit=True, connect_timeout=5
        ) as connection:
            try:
                with owner(connection, A):
                    connection.execute(
                        "select update_medication_library_pdf(%s,1,%s,'other','')", (value["id"], f"DEMO {number}")
                    )
                return "updated"
            except psycopg.errors.SerializationFailure:
                return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert sorted(results) == ["stale", "updated"]
    assert (
        db.execute(
            "select count(*) from medication_library_file_audit where file_id=%s and action='metadata_updated'",
            (value["id"],),
        ).fetchone()[0]
        == 1
    )


def test_patient_cannot_edit_audit_or_mutate_another_patients_file(db):
    value = metadata(db)
    register(db, value)
    for query, args in [
        ("select update_medication_library_pdf(%s,1,'DEMO','other','')", (value["id"],)),
        ("select tombstone_medication_library_pdf(%s,true)", (value["id"],)),
        ("delete from medication_library_file_audit where file_id=%s", (value["id"],)),
    ]:
        with pytest.raises(psycopg.Error), owner(db, B):
            db.execute(query, args)


def test_audit_failure_rolls_back_photo_retirement_and_embedding_delete(db):
    identifier, data = image(db, eligible=True)
    embed_id, _ = embedding(db, identifier, data)
    db.execute(
        "create function demo_fail_audit() returns trigger language plpgsql as $$ "
        "begin raise exception 'DEMO audit failure'; end $$"
    )
    db.execute(
        "create trigger demo_fail_audit before insert on medication_image_audit "
        "for each row execute function demo_fail_audit()"
    )
    try:
        with pytest.raises(psycopg.Error), owner(db, A):
            db.execute("select retire_personal_reference(%s)", (identifier,))
    finally:
        db.execute("drop trigger demo_fail_audit on medication_image_audit")
        db.execute("drop function demo_fail_audit()")
    assert (
        db.execute("select data->>'eligibility' from medication_images where id=%s", (identifier,)).fetchone()[0]
        == "eligible"
    )
    assert db.execute("select id from image_embeddings where id=%s", (embed_id,)).fetchone()


def test_nonempty_rollback_refuses_atomically(db):
    with pytest.raises(psycopg.Error):
        db.execute(DOWN.read_text(encoding="utf-8"))
    db.execute("ROLLBACK")
    assert db.execute("select to_regclass('medication_library_files')").fetchone()[0]
