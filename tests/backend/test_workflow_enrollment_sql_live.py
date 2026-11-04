"""Explicitly gated SQL cases; fixtures/grants must already exist on the approved target."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.contracts.assistant_workflows import WorkflowTask

from .test_workflow_enrollment_operations import values
from .test_workflow_sql import _sql_command, live_workflow_sql  # noqa: F401 — pytest fixture registration


@pytest.fixture
def live_enrollment_sql(request):
    if os.environ.get("ASSISTANT_ENROLLMENT_SQL_APPROVED") != "1":
        pytest.skip("No scoped enrollment SQL acceptance approval/target; no connection attempted")
    fixture = request.getfixturevalue("live_workflow_sql")
    connection, dsn, owners = fixture
    exists = connection.execute("select to_regclass('public.assistant_enrollment_operations')").fetchone()[0]
    assert exists is not None, "Pre-approved 036 fixture is missing; runner will not apply it"
    granted = connection.execute(
        "select has_function_privilege('authenticated',"
        "'public.assistant_enrollment_prepare_once(uuid,uuid,integer,bigint,text,text,jsonb)','EXECUTE')"
    ).fetchone()[0]
    assert granted, "Explicit target-only execution grant is missing; runner will not grant it"
    return fixture


def seed(connection, owner, h):
    fields = values().fields
    row = WorkflowTask(
        id=uuid4(),
        owner=owner,
        workspace_id=uuid4(),
        capability_id="medication.enroll",
        fields=fields.model_dump(mode="json", exclude_none=True),
        state="ready_for_review",
        storage_state="saved",
        updated_at=datetime(2026, 10, 26, tzinfo=UTC),
    )
    response = _sql_command(
        connection,
        owner,
        "task_create",
        {"task_id": str(row.id), "task": row.model_dump(mode="json", exclude={"owner"}), "suspend_foreground": True},
    )
    assert "result" in response
    prepared = h.container.enrollment.prepare_draft(patient_id=owner, draft=fields.draft).model_copy(
        update={"workflow_task_id": row.id, "workflow_revision": 1}
    )
    generation = connection.execute(
        "select coalesce((select revision from public.assistant_enrollment_generations where owner=%s),0)", (owner,)
    ).fetchone()[0]
    return row, prepared, generation


def publish(connection, owner, row, prepared, generation, key, digest="0" * 64):
    import hashlib

    from psycopg.types.json import Jsonb

    with connection.transaction():
        connection.execute("set local role authenticated")
        connection.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(owner),))
        connection.execute(
            "select set_config('request.jwt.claims',%s,true)",
            (json.dumps({"sub": str(owner), "role": "authenticated"}),),
        )
        return connection.execute(
            "select public.assistant_enrollment_prepare_once(%s,%s,%s,%s,%s,%s,%s)",
            (
                key,
                row.id,
                1,
                generation,
                digest,
                hashlib.sha256(f"pharmascan-synthetic-source::{owner}::{prepared.source.id}".encode()).hexdigest(),
                Jsonb(prepared.model_dump(mode="json")),
            ),
        ).fetchone()[0]


def test_live_enrollment_same_key_concurrency_returns_one_aggregate(live_enrollment_sql, workflow):
    import psycopg

    connection, dsn, (owner, _) = live_enrollment_sql
    row, prepared, generation = seed(connection, owner, workflow)
    key = uuid4()

    def run(_):
        with psycopg.connect(dsn, autocommit=True) as separate:
            return publish(separate, owner, row, prepared, generation, key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert results[0] == results[1] and results[0]["result"]["regimen_id"] == str(prepared.result.regimen.id)
    assert (
        connection.execute(
            "select count(*) from public.regimen_versions where patient_id=%s and id=%s",
            (owner, prepared.result.regimen.id),
        ).fetchone()[0]
        == 1
    )


def test_live_enrollment_failure_rolls_back_all_business_rows(live_enrollment_sql, workflow):
    connection, _, (owner, _) = live_enrollment_sql
    row, prepared, generation = seed(connection, owner, workflow)
    bad = prepared.model_copy(
        update={
            "result": prepared.result.model_copy(
                update={
                    "source_fields": [
                        field.model_copy(update={"source_id": uuid4()}) for field in prepared.result.source_fields
                    ]
                }
            )
        }
    )
    result = publish(connection, owner, row, bad, generation, uuid4())
    assert "error" in result
    assert (
        connection.execute(
            "select count(*) from public.source_documents where patient_id=%s and id=%s", (owner, prepared.source.id)
        ).fetchone()[0]
        == 0
    )
    assert (
        connection.execute(
            "select count(*) from public.regimen_versions where patient_id=%s and id=%s",
            (owner, prepared.result.regimen.id),
        ).fetchone()[0]
        == 0
    )


def test_live_enrollment_cross_owner_and_revoked_control_are_denied(live_enrollment_sql, workflow):
    connection, _, (owner, other) = live_enrollment_sql
    row, prepared, generation = seed(connection, owner, workflow)
    assert "error" in publish(connection, other, row, prepared, generation, uuid4())
    _sql_command(
        connection, owner, "control_revoke", {"task_id": str(row.id), "expected_revision": 1, "event_id": str(uuid4())}
    )
    assert "error" in publish(connection, owner, row, prepared, generation, uuid4())
    assert (
        connection.execute(
            "select count(*) from public.source_documents where patient_id=%s and id=%s", (owner, prepared.source.id)
        ).fetchone()[0]
        == 0
    )
