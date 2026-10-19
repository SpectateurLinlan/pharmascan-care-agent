"""Migration 030 successor activation acceptance on an isolated local PostgreSQL."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from psycopg.types.json import Jsonb

from .test_conversation_threads_sql import A, B, owner
from .test_conversation_threads_sql import db as db

pytestmark = pytest.mark.skipif(not os.environ.get("THREADS_TEST_DSN"), reason="isolated local PostgreSQL required")


def _source(c, patient: UUID, medication_name: str, dose: int, schedule: dict) -> tuple[UUID, dict[str, UUID]]:
    source_id = uuid4()
    c.execute(
        "insert into source_documents(id,patient_id,source_kind,review_status,checksum) "
        "values(%s,%s,'user_manual','extracted',%s)",
        (source_id, patient, uuid4().hex * 2),
    )
    values = {
        "medication_name": medication_name,
        "dose_amount": dose,
        "dose_unit": "mg",
        "frequency_rule": schedule,
    }
    fields: dict[str, UUID] = {}
    for name, value in values.items():
        field_id = uuid4()
        c.execute(
            "insert into source_fields(id,patient_id,source_id,field_name,field_value,evidence_locator,"
            "extraction_method) values(%s,%s,%s,%s,%s,%s,'manual')",
            (field_id, patient, source_id, name, Jsonb(value), f"synthetic:{name}"),
        )
        fields[name] = field_id
    c.execute(
        "update source_fields set review_status='user_reviewed',reviewed_at=clock_timestamp() "
        "where patient_id=%s and source_id=%s",
        (patient, source_id),
    )
    c.execute(
        "update source_documents set review_status='user_reviewed',reviewed_at=clock_timestamp() "
        "where patient_id=%s and id=%s",
        (patient, source_id),
    )
    return source_id, fields


def _session(c, patient: UUID) -> UUID:
    session_id = uuid4()
    c.execute(
        "insert into agent_sessions(id,patient_id,intent,state,prompt_version,updated_at,expires_at) "
        "values(%s,%s,'medication_enrollment','awaiting_confirmation','DEMO_successor_v1',"
        "clock_timestamp(),clock_timestamp()+interval '1 hour')",
        (session_id, patient),
    )
    return session_id


def _challenge(c, patient: UUID, regimen_id: UUID) -> UUID:
    challenge_id = uuid4()
    session_id = _session(c, patient)
    issued_at = datetime.now(UTC)
    c.execute(
        "insert into confirmation_challenges(id,patient_id,session_id,session_state_version,action,regimen_id,"
        "idempotency_key,token_hash,request_hash,issued_at,expires_at) "
        "values(%s,%s,%s,1,'activate_regimen',%s,%s,%s,%s,%s,%s)",
        (
            challenge_id,
            patient,
            session_id,
            regimen_id,
            "activate:" + uuid4().hex,
            uuid4().hex * 2,
            uuid4().hex * 2,
            issued_at,
            issued_at + timedelta(minutes=9),
        ),
    )
    c.execute(
        "update confirmation_challenges set confirmed_at=clock_timestamp() where patient_id=%s and id=%s",
        (patient, challenge_id),
    )
    return challenge_id


def _regimen(
    c,
    patient: UUID,
    medication_id: UUID,
    source_id: UUID,
    fields: dict[str, UUID],
    *,
    version: int,
    dose: int,
    schedule: dict,
    predecessor: UUID | None = None,
) -> UUID:
    regimen_id = uuid4()
    c.execute(
        "insert into regimen_versions(id,patient_id,patient_medication_id,source_id,version_no,state,dose_amount,"
        "dose_unit,frequency_rule,supersedes_id) values(%s,%s,%s,%s,%s,'draft',%s,'mg',%s,%s)",
        (regimen_id, patient, medication_id, source_id, version, dose, Jsonb(schedule), predecessor),
    )
    return regimen_id


def _make_plan(
    c, patient: UUID, medication_id: UUID | None = None, *, version: int = 1, predecessor=None, dose=5, time="08:00"
):
    schedule = {"kind": "daily", "local_times": [time], "days_of_week": [1, 2, 3, 4, 5, 6, 7]}
    medication_name = "DEMO successor " + uuid4().hex[:10]
    if medication_id is not None:
        medication_name = c.execute(
            "select display_name from patient_medications where patient_id=%s and id=%s",
            (patient, medication_id),
        ).fetchone()[0]
    source_id, fields = _source(c, patient, medication_name, dose, schedule)
    if medication_id is None:
        medication_id = uuid4()
        c.execute(
            "insert into patient_medications(id,patient_id,source_id,display_name,identity_status) "
            "values(%s,%s,%s,%s,'user_reviewed_document')",
            (medication_id, patient, source_id, medication_name),
        )
    regimen_id = _regimen(
        c,
        patient,
        medication_id,
        source_id,
        fields,
        version=version,
        dose=dose,
        schedule=schedule,
        predecessor=predecessor,
    )
    challenge_id = _challenge(c, patient, regimen_id)
    return regimen_id, challenge_id, schedule, source_id, fields, medication_name


def _activate_as(c, patient: UUID, regimen_id: UUID, challenge_id: UUID):
    with owner(c, patient):
        return c.execute(
            "select activate_medication_regimen_version(%s,%s,'Asia/Singapore')",
            (regimen_id, challenge_id),
        ).fetchone()[0]


def _activate_initial(c, patient: UUID):
    regimen_id, challenge_id, schedule, source_id, fields, name = _make_plan(c, patient)
    result = _activate_as(c, patient, regimen_id, challenge_id)
    medication_id = c.execute(
        "select patient_medication_id from regimen_versions where patient_id=%s and id=%s",
        (patient, regimen_id),
    ).fetchone()[0]
    return regimen_id, medication_id, result


def test_successor_rpc_atomically_preserves_history_and_reconciles_future_occurrences(db):
    import psycopg

    predecessor, medication_id, _ = _activate_initial(db, A)
    old_rule = db.execute(
        "select id from dose_rules where patient_id=%s and regimen_id=%s and enabled",
        (A, predecessor),
    ).fetchone()[0]
    unreported_future, reported_future = uuid4(), uuid4()
    now = datetime.now(UTC)
    for occurrence_id, due_at in (
        (unreported_future, now + timedelta(days=1)),
        (reported_future, now + timedelta(days=2)),
    ):
        db.execute(
            "insert into dose_occurrences(id,patient_id,regimen_id,rule_id,due_at,generation_key) "
            "values(%s,%s,%s,%s,%s,%s)",
            (occurrence_id, A, predecessor, old_rule, due_at, "DEMO:" + uuid4().hex),
        )
    report_session = _session(db, A)
    report_challenge = uuid4()
    report_idempotency_key = "report:" + uuid4().hex
    db.execute(
        "insert into confirmation_challenges(id,patient_id,session_id,session_state_version,action,regimen_id,"
        "occurrence_id,intended_intake_status,idempotency_key,token_hash,request_hash,issued_at,expires_at) "
        "values(%s,%s,%s,1,'record_self_report',%s,%s,'reported_taken',%s,%s,%s,%s,%s)",
        (
            report_challenge,
            A,
            report_session,
            predecessor,
            reported_future,
            report_idempotency_key,
            uuid4().hex * 2,
            uuid4().hex * 2,
            now,
            now + timedelta(minutes=9),
        ),
    )
    db.execute(
        "update confirmation_challenges set confirmed_at=clock_timestamp() where patient_id=%s and id=%s",
        (A, report_challenge),
    )
    db.execute(
        "insert into dose_events(patient_id,occurrence_id,regimen_id,confirmation_challenge_id,event_time,"
        "intake_status,idempotency_key) values(%s,%s,%s,%s,%s,'reported_taken',%s)",
        (A, reported_future, predecessor, report_challenge, now, report_idempotency_key),
    )

    successor, challenge, _, _, _, _ = _make_plan(db, A, medication_id, version=2, predecessor=predecessor, dose=10)
    before = db.execute(
        "select id,source_id,version_no,dose_amount,dose_unit,frequency_rule,effective_from from regimen_versions "
        "where patient_id=%s and id=%s",
        (A, predecessor),
    ).fetchone()
    result = _activate_as(db, A, successor, challenge)

    assert str(predecessor) in result["superseded_regimen_ids"]
    predecessor_after = db.execute(
        "select state,effective_to,id,source_id,version_no,dose_amount,dose_unit,frequency_rule,effective_from "
        "from regimen_versions where patient_id=%s and id=%s",
        (A, predecessor),
    ).fetchone()
    assert predecessor_after[0] == "superseded" and predecessor_after[1] is not None
    assert predecessor_after[2:] == before
    assert db.execute("select state from regimen_versions where id=%s", (successor,)).fetchone()[0] == "active"
    assert db.execute("select enabled from dose_rules where id=%s", (old_rule,)).fetchone()[0] is False
    statuses = dict(
        db.execute(
            "select id,status from dose_occurrences where id=any(%s)",
            ([unreported_future, reported_future],),
        ).fetchall()
    )
    assert statuses[unreported_future] == "closed"
    assert statuses[reported_future] == "scheduled"
    assert (
        db.execute(
            "select count(*) from dose_rules where patient_id=%s and regimen_id=%s and enabled",
            (A, successor),
        ).fetchone()[0]
        == 1
    )
    audit_counts = dict(
        db.execute(
            "select regimen_id,count(*) from audit_events where patient_id=%s and regimen_id=any(%s) and action in "
            "('regimen_superseded','regimen_activated') group by regimen_id",
            (A, [predecessor, successor]),
        ).fetchall()
    )
    assert audit_counts == {predecessor: 2, successor: 1}

    # The named successor exception does not permit another overlapping draft.
    schedule = {"kind": "daily", "local_times": ["08:00"], "days_of_week": [1, 2, 3, 4, 5, 6, 7]}
    source_id, _ = _source(
        db,
        A,
        db.execute("select display_name from patient_medications where id=%s", (medication_id,)).fetchone()[0],
        15,
        schedule,
    )
    with pytest.raises(psycopg.Error) as denied:
        db.execute(
            "insert into regimen_versions(patient_id,patient_medication_id,source_id,version_no,state,dose_amount,"
            "dose_unit,frequency_rule) values(%s,%s,%s,3,'draft',15,'mg',%s)",
            (A, medication_id, source_id, Jsonb(schedule)),
        )
    assert denied.value.sqlstate == "P7501"


def test_successor_rpc_failure_rolls_back_every_change_and_foreign_owner_cannot_activate(db):
    import psycopg

    predecessor, medication_id, _ = _activate_initial(db, A)
    bad_successor, bad_challenge, _, _, _, _ = _make_plan(
        db,
        A,
        medication_id,
        version=2,
        predecessor=predecessor,
        dose=10,
        time="25:99",
    )
    rules_before = db.execute("select count(*) from dose_rules where patient_id=%s", (A,)).fetchone()[0]
    audits_before = db.execute("select count(*) from audit_events where patient_id=%s", (A,)).fetchone()[0]
    with pytest.raises(psycopg.Error):
        _activate_as(db, A, bad_successor, bad_challenge)
    assert db.execute("select state,effective_to from regimen_versions where id=%s", (predecessor,)).fetchone() == (
        "active",
        None,
    )
    assert db.execute("select state from regimen_versions where id=%s", (bad_successor,)).fetchone()[0] == "draft"
    assert (
        db.execute("select consumed_at from confirmation_challenges where id=%s", (bad_challenge,)).fetchone()[0]
        is None
    )
    assert db.execute("select count(*) from dose_rules where patient_id=%s", (A,)).fetchone()[0] == rules_before
    assert db.execute("select count(*) from audit_events where patient_id=%s", (A,)).fetchone()[0] == audits_before

    successor, challenge, *_ = _make_plan(db, A, medication_id, version=3, predecessor=predecessor, dose=20)
    with pytest.raises(psycopg.Error):
        _activate_as(db, B, successor, challenge)
    assert db.execute("select state from regimen_versions where id=%s", (predecessor,)).fetchone()[0] == "active"
    assert db.execute("select state from regimen_versions where id=%s", (successor,)).fetchone()[0] == "draft"
    assert db.execute("select consumed_at from confirmation_challenges where id=%s", (challenge,)).fetchone()[0] is None


def test_successor_rpc_execute_grants_are_authenticated_only(db):
    privileges = db.execute(
        "select has_function_privilege('authenticated',"
        "'public.activate_medication_regimen_version(uuid,uuid,text)','execute'),"
        "has_function_privilege('anon','public.activate_medication_regimen_version(uuid,uuid,text)','execute'),"
        "exists(select 1 from pg_proc p join pg_namespace n on n.oid=p.pronamespace "
        "cross join lateral aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a "
        "where n.nspname='public' and p.proname='activate_medication_regimen_version' and a.grantee=0 "
        "and a.privilege_type='EXECUTE')"
    ).fetchone()
    assert privileges == (True, False, False)


def test_migration_030_rollback_restores_overlap_guard_and_can_be_reapplied(db):
    rollback = Path("supabase/rollback/202610190030_regimen_successor_activation.sql").read_text(encoding="utf-8")
    forward = Path("supabase/migrations/202610190030_regimen_successor_activation.sql").read_text(encoding="utf-8")

    db.execute(rollback)
    assert (
        db.execute("select to_regprocedure('public.activate_medication_regimen_version(uuid,uuid,text)')").fetchone()[0]
        is None
    )
    rolled_back_guard = db.execute(
        "select pg_get_functiondef('public.core_guard_regimen_overlap()'::regprocedure)"
    ).fetchone()[0]
    assert "NEW.supersedes_id IS DISTINCT FROM r.id" not in rolled_back_guard
    assert (
        db.execute(
            "select count(*) from pg_trigger where tgname='regimen_overlap_guard' and not tgisinternal"
        ).fetchone()[0]
        == 1
    )

    db.execute(forward)
    assert (
        db.execute("select to_regprocedure('public.activate_medication_regimen_version(uuid,uuid,text)')").fetchone()[0]
        is not None
    )
    reapplied_guard = db.execute(
        "select pg_get_functiondef('public.core_guard_regimen_overlap()'::regprocedure)"
    ).fetchone()[0]
    assert "NEW.supersedes_id IS DISTINCT FROM r.id" in reapplied_guard
