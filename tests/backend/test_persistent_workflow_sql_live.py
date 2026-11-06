"""Real isolated SQL definitions. Default SKIP; never provisions roles, schemas or owners."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4
from typing import get_args

import pytest
from app.contracts.assistant_workflows import BusinessRef, WorkflowTask

from tests.backend.persistent_workflow_live_support import admitted_live_profile, sql_connection_parameters

SQL = {
    name: f"SELECT public.{name}(%s)"
    for name in (
        "assistant_workflow_mutate",
        "assistant_run_control",
        "assistant_settings_prepare",
        "assistant_settings_write",
        "assistant_settings_read",
    )
}


def patient(connection, owner, name, body):
    from psycopg.types.json import Jsonb

    if name not in SQL:
        raise ValueError("Fixed patient test function required")
    with connection.transaction():
        connection.execute("SET LOCAL ROLE authenticated")
        connection.execute("SELECT set_config('request.jwt.claim.sub',%s,true)", (str(owner),))
        connection.execute(
            "SELECT set_config('request.jwt.claims',%s,true)",
            (json.dumps({"sub": str(owner), "role": "authenticated"}),),
        )
        return connection.execute(SQL[name], (Jsonb(body),)).fetchone()[0]


@pytest.fixture
def live_persistence_sql():
    profile, target = admitted_live_profile("sql_write")
    import psycopg

    try:
        connection = psycopg.connect(**sql_connection_parameters(profile, verifier=False, read_only=False))
    except psycopg.Error:
        pytest.fail("Approved isolated SQL connection unavailable", pytrace=False)
    with connection:
        from urllib.parse import urlparse

        assert connection.execute("SELECT current_database()").fetchone()[0] == urlparse(profile.database_url).path[1:]
        count = connection.execute(
            "SELECT count(*) FROM public.patient_profiles WHERE user_id=ANY(%s) AND demo_only",
            ([target.owner_a, target.owner_b],),
        ).fetchone()[0]
        assert count == 2, "Both distinct synthetic owners must already exist; no provisioning allowed"
        assert connection.execute(
            "SELECT to_regprocedure('public.assistant_workflow_mutate(jsonb)') IS NOT NULL"
        ).fetchone()[0]
        yield profile, target, connection


def seed(connection, owner, capability="source.preview", fields=None):
    task = WorkflowTask(
        id=uuid4(),
        owner=owner,
        workspace_id=uuid4(),
        capability_id=capability,
        fields=fields or {},
        state="ready_for_review",
        storage_state="saved",
        updated_at=datetime.now(UTC),
    )
    result = patient(
        connection,
        owner,
        "assistant_workflow_mutate",
        {"kind": "start", "task": task.model_dump(mode="json", exclude={"owner"})},
    )
    assert "result" in result, "Approved fixture task creation failed"
    return task


def setting(connection, owner):
    with connection.transaction():
        connection.execute("SELECT set_config('request.jwt.claim.sub',%s,true)", (str(owner),))
        previous = connection.execute("SELECT public.assistant_settings_preferences(%s)", (owner,)).fetchone()[0]
        generation = connection.execute(
            "SELECT coalesce((SELECT revision FROM public.assistant_settings_generations WHERE owner=%s),0)"
            "+coalesce((SELECT revision FROM public.assistant_enrollment_generations WHERE owner=%s),0)",
            (owner, owner),
        ).fetchone()[0]
    previous = {k: v for k, v in previous.items() if k not in {"patient_id", "created_at", "updated_at"}}
    value = "zh" if previous["preferred_language"] == "en" else "en"
    task = seed(connection, owner, "preference.language", {"preferred_language": value, "previous": previous})
    key = uuid4()
    ref = {"kind": "settings_review", "id": str(key), "version": 1}
    binding = {
        "task_id": str(task.id),
        "task_revision": 1,
        "capability_id": task.capability_id,
        "action_key": str(key),
        "prepared_ref": ref,
        "expected_domain_revision": generation,
    }
    prepared = patient(
        connection, owner, "assistant_settings_prepare", {"kind": "prepare_settings", "binding": binding}
    )
    assert "result" in prepared, "Native settings preparation refused"
    binding = binding | {
        "task_revision": 2,
        "action_key": str(uuid4()),
        "expected_domain_revision": prepared["result"]["receipt"]["domain_revision"],
    }
    return task, {
        "kind": "preferences",
        "binding": binding,
        "values": {"preferred_language": value},
        "previous": previous,
        "confirmed": True,
    }


def test_live_restricted_acl_cannot_reach_patient_or_clinical_authority(live_persistence_sql):
    from scripts.qa.inspect_assistant_evidence_scope import inspect_read_only
    from tests.backend.persistent_workflow_live_support import validate_persistent_test_profile

    profile, target, _ = live_persistence_sql
    validate_persistent_test_profile(profile, purpose="sql_read", require_hashes=True)
    result = inspect_read_only(profile, target)
    assert result["acl_observation"] == "PASS", "Restricted role/owner/PUBLIC closure is not accepted"


def test_live_invoker_identity_readers_match_native_claim_precedence(live_persistence_sql):
    """Managed Auth schema privileges are not required by the pure claim readers."""
    _, target, c = live_persistence_sql
    with c.transaction():
        c.execute("SET LOCAL ROLE authenticated")
        for top_level, claims in (
            ("", {"sub": str(target.owner_a), "role": "authenticated"}),
            (str(target.owner_b), {"sub": str(target.owner_a), "role": "authenticated"}),
            ("", {}),
        ):
            c.execute("SELECT set_config('request.jwt.claim.sub',%s,true)", (top_level,))
            c.execute("SELECT set_config('request.jwt.claims',%s,true)", (json.dumps(claims),))
            assert c.execute(
                "SELECT public.assistant_patient_uid() IS NOT DISTINCT FROM auth.uid(),"
                "public.assistant_patient_role() IS NOT DISTINCT FROM auth.role()"
            ).fetchone() == (True, True)
    assert c.execute(
        "SELECT bool_and(NOT prosecdef) FROM pg_proc "
        "WHERE oid=ANY(ARRAY['public.assistant_patient_uid()'::regprocedure,"
        "'public.assistant_patient_role()'::regprocedure])"
    ).fetchone()[0] is True
    assert c.execute(
        "SELECT has_function_privilege('assistant_evidence_login',"
        "'public.assistant_patient_uid()','EXECUTE')"
    ).fetchone()[0] is False


def test_live_preparation_reference_contract_matches_typed_application(live_persistence_sql):
    """Every typed preparation/result kind crosses the actual CHECK helper."""
    from psycopg.types.json import Jsonb

    _, _, c = live_persistence_sql
    for kind in get_args(BusinessRef.model_fields["kind"].annotation):
        assert c.execute(
            "SELECT public.assistant_wf_ref(%s)", (Jsonb({"kind": kind, "id": str(uuid4())}),)
        ).fetchone()[0] is True
    for invalid in ({"kind": "unregistered", "id": str(uuid4())},
                    {"kind": "regimen", "id": str(uuid4()), "version": 0}):
        assert c.execute("SELECT public.assistant_wf_ref(%s)", (Jsonb(invalid),)).fetchone()[0] is False


@pytest.mark.parametrize("status,reason", [("completed", None), ("failed", "execution_failed"),
                                           ("cancelled", "cancelled")])
def test_live_run_terminal_status_and_reason(live_persistence_sql, status, reason):
    from app.contracts.workflow_run_control import ClaimRun, FinishRun, RunControlState
    from app.infrastructure.workflow_verification import (
        EvidenceConnectionSettings, PostgresEvidenceVerifier, RestrictedEvidenceConnection,
    )

    profile, target, connection = live_persistence_sql
    run = uuid4()
    started = patient(connection, target.owner_a, "assistant_run_control",
                      {"kind": "start", "run_id": str(run), "task_id": None})
    initial = RunControlState.model_validate(started["result"])
    verifier = PostgresEvidenceVerifier(RestrictedEvidenceConnection(EvidenceConnectionSettings(profile.evidence_dsn)))
    claimed = verifier.record_run(ClaimRun(ticket_id=initial.worker_ticket, nonce=initial.worker_nonce,
                                         epoch=0, event_id=uuid4()), timeout_seconds=3)
    finished = verifier.record_run(FinishRun(ticket_id=claimed.worker_ticket, nonce=claimed.worker_nonce,
                                          epoch=claimed.epoch, event_id=uuid4(), status=status,
                                          reason=reason, duration_ms=1), timeout_seconds=3)
    assert finished.status == status
    assert finished.snapshot.events[-1].reason_key == reason
    assert finished.snapshot.events[-1].kind == "run_" + status


def test_live_cross_owner_task_and_forged_result_are_rejected(live_persistence_sql):
    from .test_workflow_sql import _sql_command

    _, target, c = live_persistence_sql
    task = seed(c, target.owner_a)
    assert _sql_command(c, target.owner_b, "task_get", {"task_id": str(task.id)}) == {"error": "not_found"}
    bad = patient(
        c,
        target.owner_a,
        "assistant_workflow_mutate",
        {"kind": "complete_business", "task_id": str(task.id), "confirmed": True},
    )
    assert "error" in bad
    assert (
        c.execute(
            "SELECT count(*) FROM public.assistant_business_receipts WHERE owner=%s AND task_id=%s",
            (target.owner_a, task.id),
        ).fetchone()[0]
        == 0
    )


def test_live_native_result_response_recovery_and_changed_body_do_not_repeat_write(live_persistence_sql):
    _, target, c = live_persistence_sql
    task, command = setting(c, target.owner_a)
    first = patient(c, target.owner_a, "assistant_settings_write", command)
    assert "result" in first
    replay = patient(c, target.owner_a, "assistant_settings_read", command)
    assert replay["result"] == first["result"]
    changed = command | {"values": {"preferred_language": command["previous"]["preferred_language"]}}
    assert "error" in patient(c, target.owner_a, "assistant_settings_write", changed)
    assert (
        c.execute(
            "SELECT count(*) FROM public.assistant_business_receipts WHERE owner=%s AND action_key=%s",
            (target.owner_a, command["binding"]["action_key"]),
        ).fetchone()[0]
        == 1
    )
    assert (
        c.execute(
            "SELECT (data->>'revision')::int FROM public.assistant_workflow_tasks WHERE owner=%s AND id=%s",
            (target.owner_a, task.id),
        ).fetchone()[0]
        == 3
    )


def test_live_native_task_and_receipt_rollback_with_caller_transaction(live_persistence_sql):
    import psycopg

    _, target, c = live_persistence_sql
    task, command = setting(c, target.owner_a)
    before = c.execute("SELECT language FROM public.patient_profiles WHERE user_id=%s", (target.owner_a,)).fetchone()[0]
    with c.transaction():
        assert "result" in patient(c, target.owner_a, "assistant_settings_write", command)
        raise psycopg.Rollback()
    assert (
        c.execute("SELECT language FROM public.patient_profiles WHERE user_id=%s", (target.owner_a,)).fetchone()[0]
        == before
    )
    assert (
        c.execute(
            "SELECT count(*) FROM public.assistant_business_receipts WHERE owner=%s AND action_key=%s",
            (target.owner_a, command["binding"]["action_key"]),
        ).fetchone()[0]
        == 0
    )
    assert (
        c.execute(
            "SELECT (data->>'revision')::int FROM public.assistant_workflow_tasks WHERE owner=%s AND id=%s",
            (target.owner_a, task.id),
        ).fetchone()[0]
        == 2
    )


def test_live_two_instances_concurrently_publish_one_actual_native_result(live_persistence_sql):
    import psycopg

    profile, target, c = live_persistence_sql
    _, command = setting(c, target.owner_a)

    def attempt(_):
        with psycopg.connect(**sql_connection_parameters(profile, verifier=False, read_only=False)) as other:
            return patient(other, target.owner_a, "assistant_settings_write", command)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert all("result" in r for r in results) and results[0]["result"] == results[1]["result"]
    assert (
        c.execute(
            "SELECT count(*) FROM public.assistant_business_receipts WHERE owner=%s AND action_key=%s",
            (target.owner_a, command["binding"]["action_key"]),
        ).fetchone()[0]
        == 1
    )


def test_live_cancel_is_shared_and_old_worker_epoch_is_rejected(live_persistence_sql):
    import psycopg
    from app.contracts.workflow_run_control import ClaimRun, RunControlState, StartRunStep
    from app.domain.errors import DomainError
    from app.infrastructure.workflow_verification import (
        EvidenceConnectionSettings,
        PostgresEvidenceVerifier,
        RestrictedEvidenceConnection,
    )

    profile, target, c = live_persistence_sql
    run_id = uuid4()
    started = patient(
        c, target.owner_a, "assistant_run_control", {"kind": "start", "run_id": str(run_id), "task_id": None}
    )
    state = RunControlState.model_validate(started["result"])
    verifier = PostgresEvidenceVerifier(RestrictedEvidenceConnection(EvidenceConnectionSettings(profile.evidence_dsn)))
    claimed = verifier.record_run(
        ClaimRun(ticket_id=state.worker_ticket, nonce=state.worker_nonce, epoch=state.epoch, event_id=uuid4()),
        timeout_seconds=3,
    )
    with psycopg.connect(**sql_connection_parameters(profile, verifier=False, read_only=False)) as other:
        cancelled = patient(other, target.owner_a, "assistant_run_control", {"kind": "cancel", "run_id": str(run_id)})
    current = patient(c, target.owner_a, "assistant_run_control", {"kind": "read", "run_id": str(run_id)})
    assert current["result"]["status"] == cancelled["result"]["status"] and current["result"]["status"] != "running"
    with pytest.raises(DomainError):
        verifier.record_run(
            StartRunStep(
                ticket_id=claimed.worker_ticket,
                nonce=claimed.worker_nonce,
                epoch=claimed.epoch,
                event_id=uuid4(),
                span_id=uuid4(),
                step_kind="tool",
            ),
            timeout_seconds=3,
        )


def test_live_nonempty_down_guard_refuses_without_executing_drop(request):
    import os
    import re

    import psycopg

    from tests.backend.persistent_workflow_live_support import ROOT, admitted_live_profile

    if os.environ.get("ASSISTANT_PERSISTENCE_DOWN_APPROVED") != "1":
        pytest.skip("Separate down-probe approval absent; no connecting fixture requested")
    admitted_live_profile("down_probe")  # Separate explicit scope, even on an approved SQL target.
    _, target, c = request.getfixturevalue("live_persistence_sql")
    setting(c, target.owner_a)
    source = (ROOT / "supabase/review/assistant_workflows/metadata.down.sql").read_text(encoding="utf-8")
    guard = re.search(r"DO \$\$.*?END \$\$;", source, re.S).group()
    with pytest.raises(psycopg.Error):
        with c.transaction():
            c.execute(guard)


@pytest.mark.parametrize(
    "change",
    [
        "ALTER TABLE public.assistant_workflow_tasks DISABLE TRIGGER assistant_original_reference_task",
        "ALTER POLICY assistant_workflow_tasks_owner ON public.assistant_workflow_tasks USING(false)",
        "REVOKE SELECT ON public.assistant_workflow_tasks FROM authenticated",
        "ALTER TABLE public.assistant_workflow_tasks ADD CONSTRAINT local_demo_drift CHECK(owner IS NOT NULL)",
        "CREATE VIEW public.medithread_local_drift_probe AS SELECT 1 AS demo_value",
    ],
    ids=("trigger", "policy", "acl", "constraint", "rewrite"),
)
def test_live_local_catalog_drift_revokes_admission_and_rollback_restores_it(request, change):
    """Uncommitted local operator marker; never publishes acceptance to other sessions."""
    import psycopg

    profile, _ = admitted_live_profile("sql_write")
    if profile.target_mode != "local_supabase":
        pytest.skip("Catalog mutation probes are approved only for the dedicated local DEMO instance")
    _, _, connection = request.getfixturevalue("live_persistence_sql")
    read = "SELECT assistant_evidence.runtime_readiness()"
    baseline = connection.execute(read).fetchone()[0]
    assert baseline["accepted"] is False, (
        "Run catalog acceptance before operator publication; preserve existing release"
    )
    with connection.transaction():
        connection.execute(
            "INSERT INTO assistant_evidence.runtime_releases "
            "(release_id,contract_version,application_hash,catalog_digest,evidence_digest,"
            "native_media_ready,accepted_at) "
            "VALUES(%s,'assistant-persistence-v1',%s,%s,%s,false,clock_timestamp())",
            (uuid4(), "a" * 64, baseline["catalog_digest"], "b" * 64),
        )
        assert connection.execute(read).fetchone()[0]["accepted"] is True
        with connection.transaction():
            connection.execute(change)
            changed = connection.execute(read).fetchone()[0]
            assert changed["accepted"] is False and changed["catalog_digest"] != baseline["catalog_digest"]
            raise psycopg.Rollback()
        restored = connection.execute(read).fetchone()[0]
        assert restored["accepted"] is True and restored["catalog_digest"] == baseline["catalog_digest"]
        raise psycopg.Rollback()
    assert connection.execute(read).fetchone()[0]["accepted"] is False
