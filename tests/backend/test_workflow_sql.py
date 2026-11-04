"""Offline PostgREST binding checks; live SQL acceptance is explicitly opt-in."""

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from app.contracts.assistant_workflows import WorkflowTask, WorkflowUpdate
from app.domain.errors import AuthenticationRequiredError, ProviderUnavailableError, StaleVersionError
from app.infrastructure.supabase_data import SupabaseDataClient
from app.infrastructure.workflow_repos import SupabaseWorkflowRepository


@pytest.mark.parametrize("clinical_revision", [None, 0])
def test_action_wire_compatibility_does_not_silently_drop_a_required_clinical_fence(clinical_revision):
    import json

    from app.contracts.assistant_workflows import ActionReceipt, WorkflowContext
    from app.infrastructure.workflow_repos import SupabaseActionRepository

    row = task()
    calls = []

    def remote(request):
        calls.append(request)
        assert "clinical_revision" not in json.loads(request.content)["p_input"]["receipt"]
        return httpx.Response(200, json={"result": None})

    data = repository(row, remote)._data
    actions = SupabaseActionRepository(data)
    context = WorkflowContext(owner=row.owner, task_id=row.id, revision=1, capability_id=row.capability_id)
    receipt = ActionReceipt(
        action_key=uuid4(),
        owner=row.owner,
        task_id=row.id,
        capability_id=row.capability_id,
        binding_revision=1,
        state="pending",
        updated_at=row.updated_at,
        clinical_revision=clinical_revision,
    )
    if clinical_revision is None:
        actions.complete(context, receipt)
        assert len(calls) == 1
    else:
        with pytest.raises(ProviderUnavailableError):
            actions.complete(context, receipt)
        assert not calls


def task(owner=None):
    return WorkflowTask(
        id=uuid4(),
        owner=owner or uuid4(),
        workspace_id=uuid4(),
        capability_id="medication.enroll",
        fields={"medication_name": "DEMO medication"},
        updated_at=datetime(2026, 10, 26, tzinfo=UTC),
    )


def repository(row, remote):
    data = SupabaseDataClient(
        base_url="https://demo-test.supabase.co",
        publishable_key="sb_publishable_DEMO",
        access_token="DEMO-owner-token",
        patient_id=row.owner,
        client=httpx.Client(transport=httpx.MockTransport(remote)),
    )
    return SupabaseWorkflowRepository(data)


def test_cas_uses_one_fixed_rpc_and_server_owner_not_a_payload_owner():
    import json

    row = task()
    requests = []

    def remote(request):
        requests.append(request)
        return httpx.Response(200, json={"result": row.model_copy(update={"revision": 2}).model_dump(mode="json")})

    repo = repository(row, remote)
    updated = repo.cas(
        row.owner,
        row.id,
        1,
        uuid4(),
        WorkflowUpdate(
            state="collecting",
            save_mode="allowed",
            storage_state="saved",
            fields={"medication_name": "DEMO medication"},
        ),
        "a" * 64,
    )
    assert updated.revision == 2 and len(requests) == 1
    assert requests[0].url.path == "/rest/v1/rpc/assistant_workflow_command"
    payload = json.loads(requests[0].content)
    assert payload["p_operation"] == "task_cas"
    assert payload["p_input"]["expected_revision"] == 1
    assert "owner" not in payload["p_input"] and "sql" not in payload["p_input"]


def test_malformed_or_cross_owner_rows_are_never_returned_as_owned_tasks():
    row = task()
    for returned in ({"unexpected": "DEMO"}, task().model_dump(mode="json")):
        repo = repository(row, lambda request, returned=returned: httpx.Response(200, json={"result": returned}))
        with pytest.raises(ProviderUnavailableError):
            repo.get(row.owner, row.id)


def test_owner_mismatch_and_stale_revision_fail_closed_without_automatic_retry():
    row = task()
    requests = []

    def remote(request):
        requests.append(request)
        return httpx.Response(200, json={"error": "stale"})

    repo = repository(row, remote)
    with pytest.raises(AuthenticationRequiredError):
        repo.get(uuid4(), row.id)
    assert requests == []
    with pytest.raises(StaleVersionError):
        repo.cas(
            row.owner,
            row.id,
            1,
            uuid4(),
            WorkflowUpdate(state="collecting", save_mode="allowed", storage_state="saved", fields={}),
        )
    assert len(requests) == 1


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://postgres@production.example:55439/mt_assistant_test_demo",
        "postgresql://postgres@127.0.0.1:5432/mt_assistant_test_demo",
        "postgresql://postgres@127.0.0.1:55439/postgres",
        "postgresql://postgres@127.0.0.1:55439/mt_assistant_test_demo?host=production.example",
        "postgresql://postgres@127.0.0.1:55439/mt_assistant_test_demo%2fother",
    ],
)
def test_live_sql_target_guard_rejects_ambiguous_destinations_before_connecting(dsn):
    from .workflow_live_support import sql_target

    with pytest.raises(ValueError):
        sql_target(dsn)


def test_persistent_content_callback_remains_denied_until_an_atomic_remote_boundary_exists():
    from app.infrastructure.workflow_repos import SupabaseControlRepository

    row = task()
    repo = repository(row, lambda request: pytest.fail("No network is needed to deny an unsupported guard"))
    controls = SupabaseControlRepository(repo._data)
    called = []
    assert controls.guarded_write(row.owner, row.id, 1, lambda: called.append("DEMO secret body")) is False
    assert called == []


def test_original_read_rejects_a_different_attachment_id_with_the_same_owner_and_task():
    from app.contracts.workflow_attachments import OriginalAttachment
    from app.infrastructure.workflow_repos import SupabaseOriginalRepository

    row = task()
    original_id = uuid4()
    returned = OriginalAttachment(
        id=original_id,
        owner=row.owner,
        task_id=row.id,
        upload_id=uuid4(),
        binding_revision=1,
        object_ref=f"{row.owner}/workflow-originals/{row.id}/{original_id}",
        original_checksum="a" * 64,
        content_type="image/png",
        source_kind="package",
        byte_size=20,
    )
    payload = returned.model_dump(mode="json") | {"object_ref": returned.object_ref}
    repo = repository(row, lambda request: httpx.Response(200, json={"result": payload}))
    with pytest.raises(ProviderUnavailableError):
        SupabaseOriginalRepository(repo._data).get(row.owner, row.id, uuid4())
    assert SupabaseOriginalRepository(repo._data).get(row.owner, row.id, original_id).id == original_id


def test_malformed_error_envelope_is_reported_as_unavailable():
    row = task()
    repo = repository(row, lambda request: httpx.Response(200, json={"error": {"DEMO": "unexpected"}}))
    with pytest.raises(ProviderUnavailableError):
        repo.get(row.owner, row.id)


@pytest.mark.parametrize("record_type", ["action", "cleanup"])
def test_unproven_terminal_persistence_receipts_are_denied_before_network(record_type):
    from app.contracts.assistant_workflows import ActionReceipt, WorkflowContext
    from app.contracts.workflow_attachments import CleanupReceipt
    from app.infrastructure.workflow_repos import SupabaseActionRepository, SupabaseCleanupRepository

    row = task()
    requests = []
    repo = repository(row, lambda request: requests.append(request) or httpx.Response(200, json={"result": None}))
    with pytest.raises(ProviderUnavailableError):
        if record_type == "action":
            context = WorkflowContext(owner=row.owner, task_id=row.id, capability_id=row.capability_id, revision=1)
            receipt = ActionReceipt(
                owner=row.owner,
                task_id=row.id,
                action_key=uuid4(),
                capability_id=row.capability_id,
                binding_revision=1,
                state="succeeded",
                updated_at=row.updated_at,
            )
            SupabaseActionRepository(repo._data).complete(context, receipt)
        else:
            original_id = uuid4()
            receipt = CleanupReceipt(
                id=original_id,
                owner=row.owner,
                task_id=row.id,
                content_type="image/png",
                state="deleted",
                object_ref=f"{row.owner}/workflow-originals/{row.id}/{original_id}",
            )
            SupabaseCleanupRepository(repo._data).update(receipt)
    assert requests == []


@pytest.fixture(scope="module")
def live_workflow_sql():
    import os
    from uuid import UUID

    import psycopg

    from .workflow_live_support import sql_target

    if os.environ.get("RUN_ASSISTANT_SQL_TESTS") != "1":
        pytest.skip("NOT_RUN: explicit isolated assistant SQL scope/target required")
    dsn = os.environ.get("ASSISTANT_TEST_DATABASE_URL", "")
    name = sql_target(dsn)
    owners = tuple(UUID(os.environ[key]) for key in ("ASSISTANT_TEST_OWNER_A", "ASSISTANT_TEST_OWNER_B"))
    assert owners[0] != owners[1]
    with psycopg.connect(dsn, autocommit=True) as connection:
        assert connection.execute("select current_database()").fetchone()[0] == name
        assert connection.execute("select to_regprocedure('public.assistant_workflow_command(text,jsonb)')").fetchone()[
            0
        ]
        assert (
            connection.execute(
                "select count(*) from public.patient_profiles where user_id=ANY(%s) and demo_only", (list(owners),)
            ).fetchone()[0]
            == 2
        )
        yield connection, dsn, owners


def _sql_command(connection, owner, operation, values):
    import json

    from psycopg.types.json import Jsonb

    with connection.transaction():
        connection.execute("SET LOCAL ROLE authenticated")
        connection.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(owner),))
        connection.execute(
            "select set_config('request.jwt.claims',%s,true)",
            (json.dumps({"sub": str(owner), "role": "authenticated"}),),
        )
        return connection.execute(
            "select public.assistant_workflow_command(%s,%s)", (operation, Jsonb(values))
        ).fetchone()[0]


def _sql_seed(connection, owner):
    row = task(owner)
    values = {
        "task_id": str(row.id),
        "task": row.model_dump(mode="json", exclude={"owner"}),
        "suspend_foreground": True,
    }
    result = _sql_command(connection, owner, "task_create", values)
    assert result["result"]["owner"] == str(owner)
    return row


def test_live_sql_owner_isolation_and_control_body_rejection(live_workflow_sql):
    connection, _, (owner_a, owner_b) = live_workflow_sql
    row = _sql_seed(connection, owner_a)
    assert _sql_command(connection, owner_b, "task_get", {"task_id": str(row.id)}) == {"error": "not_found"}
    assert _sql_command(
        connection,
        owner_b,
        "task_cas",
        {"task_id": str(row.id), "expected_revision": 1, "event_id": str(uuid4()), "update": {}},
    ) == {"error": "not_found"}
    from app.contracts.assistant_workflows import ControlReceipt

    receipt = ControlReceipt(
        owner=owner_a, task_id=uuid4(), revision=1, capability_id="medication.enroll", mode="ephemeral"
    )
    forbidden = receipt.model_dump(mode="json", exclude={"owner"}) | {
        "fields": {"medication_name": "DEMO forbidden body"}
    }
    assert _sql_command(
        connection, owner_a, "control_create", {"task_id": str(receipt.task_id), "receipt": forbidden}
    ) == {"error": "invalid"}


def test_live_sql_same_revision_has_exactly_one_winner(live_workflow_sql):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    import psycopg

    connection, dsn, (owner_a, _) = live_workflow_sql
    row = _sql_seed(connection, owner_a)
    barrier = Barrier(2)

    def advance(_):
        with psycopg.connect(dsn, autocommit=True) as concurrent:
            barrier.wait(timeout=10)
            return _sql_command(
                concurrent,
                owner_a,
                "task_cas",
                {
                    "task_id": str(row.id),
                    "expected_revision": 1,
                    "event_id": str(uuid4()),
                    "update": {
                        "state": "collecting",
                        "save_mode": "allowed",
                        "storage_state": "saved",
                        "fields": {},
                        "missing_fields": [],
                        "attachment_ids": [],
                        "business_refs": [],
                    },
                },
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(advance, range(2)))
    assert sum("result" in result for result in results) == 1
    assert sum(result == {"error": "stale"} for result in results) == 1


def test_live_sql_duplicate_action_reservation_retains_one_receipt(live_workflow_sql):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    import psycopg

    connection, dsn, (owner_a, _) = live_workflow_sql
    row = _sql_seed(connection, owner_a)
    key = uuid4()
    barrier = Barrier(2)

    def reserve(_):
        with psycopg.connect(dsn, autocommit=True) as concurrent:
            barrier.wait(timeout=10)
            return _sql_command(
                concurrent,
                owner_a,
                "action_reserve",
                {
                    "action_key": str(key),
                    "context": {
                        "task_id": str(row.id),
                        "capability_id": row.capability_id,
                        "revision": 1,
                        "save_mode": "allowed",
                        "language": "en",
                        "timezone": "UTC",
                    },
                },
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, range(2)))
    assert results[0] == results[1] and results[0]["result"]["state"] == "pending"
    receipts = _sql_command(connection, owner_a, "action_list", {"task_id": str(row.id)})["result"]
    assert len(receipts) == 1


def test_live_sql_nonempty_down_refuses_data_removal(live_workflow_sql):
    from pathlib import Path

    import psycopg

    connection, _, (owner_a, _) = live_workflow_sql
    row = _sql_seed(connection, owner_a)
    down = Path("supabase/rollback/202610250035_assistant_workflows_down.sql").read_text(encoding="utf-8")
    try:
        with pytest.raises(psycopg.errors.RaiseException, match="Workflow records remain"):
            connection.execute(down)
    finally:
        connection.execute("ROLLBACK")
    assert _sql_command(connection, owner_a, "task_get", {"task_id": str(row.id)})["result"]["id"] == str(row.id)


def _sql_original(connection, owner, row):
    from app.contracts.workflow_attachments import OriginalAttachment

    original_id, upload_id = uuid4(), uuid4()
    original = OriginalAttachment(
        id=original_id,
        owner=owner,
        task_id=row.id,
        upload_id=upload_id,
        binding_revision=1,
        object_ref=f"{owner}/workflow-originals/{row.id}/{original_id}",
        original_checksum="a" * 64,
        content_type="image/png",
        source_kind="package",
        byte_size=20,
    )
    context = {"task_id": str(row.id), "capability_id": row.capability_id, "revision": 1, "save_mode": "allowed"}
    values = original.model_dump(mode="json", exclude={"owner"}) | {"object_ref": original.object_ref}
    reserved = _sql_command(connection, owner, "original_reserve", {"context": context, "attachment": values})["result"]
    assert (
        _sql_command(
            connection, owner, "original_written", {"task_id": str(row.id), "attachment_id": str(original_id)}
        )["result"]
        is True
    )
    reserved.pop("owner")
    result = _sql_command(
        connection, owner, "original_publish", {"context": context, "attachment": reserved, "event_id": str(upload_id)}
    )
    assert result["result"]["id"] == str(original_id)
    return result["result"], context | {"revision": 2}


def test_live_sql_refuses_unproven_terminal_action_and_cleanup_receipts(live_workflow_sql):
    connection, _, (owner_a, _) = live_workflow_sql
    row = _sql_seed(connection, owner_a)
    context = {"task_id": str(row.id), "capability_id": row.capability_id, "revision": 1, "save_mode": "allowed"}
    action = _sql_command(connection, owner_a, "action_reserve", {"action_key": str(uuid4()), "context": context})[
        "result"
    ]
    action.pop("owner")
    action["state"] = "succeeded"
    assert _sql_command(connection, owner_a, "action_complete", {"context": context, "receipt": action}) == {
        "error": "unavailable"
    }
    other = _sql_seed(connection, owner_a)
    original, context = _sql_original(connection, owner_a, other)
    _sql_command(
        connection,
        owner_a,
        "control_revoke",
        {"task_id": str(other.id), "expected_revision": 2, "event_id": str(uuid4())},
    )
    receipt = _sql_command(connection, owner_a, "cleanup_get", {"attachment_id": original["id"]})["result"]
    receipt.pop("owner")
    receipt.update(state="deleted", reason="removed", writer_pending=False)
    assert _sql_command(connection, owner_a, "cleanup_update", {"receipt": receipt}) == {"error": "unavailable"}
    assert (
        _sql_command(connection, owner_a, "cleanup_get", {"attachment_id": original["id"]})["result"]["state"]
        == "pending"
    )


def test_live_sql_reviewed_source_protection_is_owned_and_monotonic(live_workflow_sql):
    connection, _, (owner_a, owner_b) = live_workflow_sql
    source_a, source_b = uuid4(), uuid4()
    for owner_id, source_id in ((owner_a, source_a), (owner_b, source_b)):
        connection.execute(
            "insert into public.source_documents(id,patient_id,source_kind,review_status,reviewed_at,checksum) "
            "values(%s,%s,'user_manual','user_reviewed',clock_timestamp(),%s)",
            (source_id, owner_id, uuid4().hex * 2),
        )
    row = _sql_seed(connection, owner_a)
    original, context = _sql_original(connection, owner_a, row)
    ref = {"kind": "source", "id": str(source_a), "version": None}
    protected = _sql_command(
        connection,
        owner_a,
        "original_protect",
        {"context": context, "attachment_id": original["id"], "source_ref": ref, "event_id": str(uuid4())},
    )
    assert protected["result"]["source_ref"] == ref
    for replacement in (None, {"kind": "source", "id": str(source_b), "version": None}):
        refused = _sql_command(
            connection,
            owner_a,
            "original_protect",
            {
                "context": context | {"revision": 3},
                "attachment_id": original["id"],
                "source_ref": replacement,
                "event_id": str(uuid4()),
            },
        )
        assert refused.get("error") in {"invalid", "duplicate"}
    current = _sql_command(
        connection, owner_a, "original_get", {"task_id": str(row.id), "attachment_id": original["id"]}
    )["result"]
    assert current["source_ref"] == ref
