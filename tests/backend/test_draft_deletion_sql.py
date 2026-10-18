"""Real isolated PostgreSQL; no remote DSN, patient or production operations."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from .test_conversation_threads_sql import A, B, owner
from .test_conversation_threads_sql import db as db

pytestmark = pytest.mark.skipif(not os.environ.get("THREADS_TEST_DSN"), reason="isolated SQL required")


def seed(c):
    src, med, plan = uuid4(), uuid4(), uuid4()
    c.execute(
        "insert into source_documents(id,patient_id,source_kind,review_status,checksum) "
        "values(%s,%s,'user_manual','extracted',repeat(replace(gen_random_uuid()::text,'-',''),2))",
        (src, A),
    )
    c.execute(
        "insert into patient_medications(id,patient_id,source_id,display_name) values(%s,%s,%s,'DEMO deletion')",
        (med, A, src),
    )
    c.execute(
        "insert into "
        "regimen_versions(id,patient_id,patient_medication_id,source_id,version_no,state,is_prn) "
        "values(%s,%s,%s,%s,1,'draft',true)",
        (plan, A, med, src),
    )
    return src, med, plan


def delete(c, plan, patient=A):
    with owner(c, patient):
        return c.execute("select delete_unconfirmed_medication('draft',%s,true)", (plan,)).fetchone()[0]


def test_reviewed_unconfirmed_draft_really_removes_exclusive_db_rows_and_retries(db):
    src, med, plan = seed(db)
    db.execute("update source_documents set review_status='user_reviewed',reviewed_at=now() where id=%s", (src,))
    result = delete(db, plan)
    assert result["deleted"] and result["medication_deleted"] and not result["storage_paths"]
    assert db.execute("select count(*) from regimen_versions where id=%s", (plan,)).fetchone()[0] == 0
    assert db.execute("select count(*) from patient_medications where id=%s", (med,)).fetchone()[0] == 0
    assert db.execute("select count(*) from source_documents where id=%s", (src,)).fetchone()[0] == 0
    assert delete(db, plan) == result


def test_direct_delete_and_cross_patient_are_denied(db):
    import psycopg

    src, med, plan = seed(db)
    with pytest.raises(psycopg.Error) as denied:
        with owner(db, A):
            db.execute("delete from regimen_versions where id=%s", (plan,))
    assert denied.value.sqlstate == "42501"
    with pytest.raises(psycopg.Error) as denied:
        delete(db, plan, B)
    assert denied.value.sqlstate == "P7504"
    assert db.execute("select count(*) from regimen_versions where id=%s", (plan,)).fetchone()[0] == 1


def test_audit_link_refuses_entire_operation_without_partial_deletion(db):
    import psycopg

    src, med, plan = seed(db)
    session = uuid4()
    db.execute(
        "insert into agent_sessions(id,patient_id,state,prompt_version,expires_at) "
        "values(%s,%s,'collecting','DEMO',now()+interval '1 hour')",
        (session, A),
    )
    db.execute(
        "insert into audit_events(patient_id,session_id,correlation_id,actor_type,action,regimen_id) "
        "values(%s,%s,%s,'backend','draft_created',%s)",
        (A, session, uuid4(), plan),
    )
    with pytest.raises(psycopg.Error) as denied:
        delete(db, plan)
    assert denied.value.sqlstate == "P7502"
    assert db.execute("select count(*) from source_documents where id=%s", (src,)).fetchone()[0] == 1
    assert db.execute("select count(*) from patient_medications where id=%s", (med,)).fetchone()[0] == 1


def test_concurrent_delete_is_atomic_and_idempotent(db):
    import psycopg

    src, med, plan = seed(db)

    def perform(_):
        with psycopg.connect(f"postgresql://postgres@127.0.0.1:55439/{db.info.dbname}", autocommit=True) as c:
            return delete(c, plan)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(perform, range(2)))
    assert results[0] == results[1] and results[0]["deleted"]


def test_storage_cleanup_receipt_survives_and_ack_is_owner_scoped(db):
    from psycopg.types.json import Jsonb

    src, med, plan = seed(db)
    image = uuid4()
    path = f"{A}/DEMO/image.png"
    data = {"id": str(image), "patient_id": str(A), "medication_id": str(med), "storage_path": path}
    db.execute(
        "insert into medication_images(id,patient_id,medication_id,source_id,data) values(%s,%s,%s,%s,%s)",
        (image, A, med, src, Jsonb(data)),
    )
    result = delete(db, plan)
    assert result["storage_paths"] == [path]
    assert db.execute("select count(*) from medication_images where id=%s", (image,)).fetchone()[0] == 0
    with owner(db, B):
        db.execute("select ack_draft_image_cleanup('draft',%s,%s)", (plan, path))
    assert delete(db, plan)["storage_paths"] == [path]
    with owner(db, A):
        db.execute("select ack_draft_image_cleanup('draft',%s,%s)", (plan, path))
    assert delete(db, plan)["storage_paths"] == []


def activate_seed(c):
    from psycopg.types.json import Jsonb

    src, med, plan = seed(c)
    bindings = []
    for field, value in [
        ("medication_name", "DEMO deletion"),
        ("dose_amount", 1),
        ("dose_unit", "tablet"),
        ("is_prn", True),
    ]:
        identity = uuid4()
        bindings.append(identity)
        c.execute(
            "insert into "
            "source_fields(id,patient_id,source_id,field_name,field_value,evidence_locator,"
            "extraction_method,review_status) "
            "values(%s,%s,%s,%s,%s,'synthetic:DEMO','manual','extracted')",
            (identity, A, src, field, Jsonb(value)),
        )
    c.execute("update source_fields set review_status='user_reviewed',reviewed_at=now() where source_id=%s", (src,))
    c.execute("update source_documents set review_status='user_reviewed',reviewed_at=now() where id=%s", (src,))
    c.execute("update patient_medications set identity_status='user_reviewed_document' where id=%s", (med,))
    session, challenge = uuid4(), uuid4()
    c.execute(
        "insert into agent_sessions(id,patient_id,state,prompt_version,expires_at) "
        "values(%s,%s,'awaiting_confirmation','DEMO',now()+interval '1 hour')",
        (session, A),
    )
    c.execute(
        "insert into "
        "confirmation_challenges(id,patient_id,session_id,session_state_version,action,regimen_id,"
        "idempotency_key,token_hash,request_hash,expires_at) "
        "values(%s,%s,%s,1,'activate_regimen',%s,%s,%s,%s,now()+interval '5 minutes')",
        (challenge, A, session, plan, "DEMO:" + str(challenge), challenge.hex * 2, challenge.hex * 2),
    )
    c.execute("update confirmation_challenges set confirmed_at=now() where id=%s", (challenge,))
    with owner(c, A):
        c.execute(
            "update regimen_versions set "
            "state='active',dose_amount=1,dose_unit='tablet',medication_name_field_id=%s,"
            "quantity_field_id=%s,unit_field_id=%s,prn_field_id=%s,source_reviewed_at=(select "
            "reviewed_at from source_documents where "
            "id=%s),effective_from=now(),confirmation_challenge_id=%s where id=%s",
            (*bindings, src, challenge, plan),
        )
    return src, med, plan


def test_confirmed_plan_refused_and_real_duplicate_guard_still_applies(db):
    import psycopg

    src, med, plan = activate_seed(db)
    with pytest.raises(psycopg.Error) as protected:
        delete(db, plan)
    assert protected.value.sqlstate == "P7502"
    with pytest.raises(psycopg.Error) as duplicate:
        with db.transaction():
            seed(db)
    assert duplicate.value.sqlstate == "P7501"
    assert db.execute("select state from regimen_versions where id=%s", (plan,)).fetchone()[0] == "active"
