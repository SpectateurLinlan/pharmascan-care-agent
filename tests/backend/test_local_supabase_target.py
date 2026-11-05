"""DEMO_ONLY: local acceptance never inherits authority from legacy profiles."""

import copy
import json
import subprocess
from dataclasses import replace
from importlib import import_module
from importlib.util import find_spec

import httpx
import psycopg
import pytest

from tests.backend.persistent_workflow_live_support import (
    PersistentProfileRefusal,
    PersistentWorkflowTestProfile,
    validate_persistent_test_profile,
)
from tests.backend.test_persistent_workflow_profile import jwt, values


@pytest.mark.parametrize("mode", ["local_supabase", "production", "", "LEGACY"])
def test_unadmitted_target_mode_cannot_fall_through_to_legacy(mode, monkeypatch):
    """Ignoring an explicit mode could connect to a different authorized dataset."""

    def no_external_io(*args, **kwargs):
        pytest.fail("Unadmitted target attempted external I/O")

    monkeypatch.setattr(httpx.Client, "request", no_external_io)
    monkeypatch.setattr(psycopg, "connect", no_external_io)
    monkeypatch.setattr(subprocess, "run", no_external_io)
    profile = PersistentWorkflowTestProfile.from_values(values() | {"ASSISTANT_TEST_TARGET_MODE": mode})

    with pytest.raises(PersistentProfileRefusal, match="target_not_authorized"):
        validate_persistent_test_profile(profile, purpose="sql_write")


def test_explicit_legacy_mode_preserves_existing_target_restrictions():
    profile = PersistentWorkflowTestProfile.from_values(values() | {"ASSISTANT_TEST_TARGET_MODE": "legacy"})
    target = validate_persistent_test_profile(profile, purpose="sql_write")
    assert target.owner_a.int == 1

    with pytest.raises(PersistentProfileRefusal):
        validate_persistent_test_profile(
            replace(profile, database_url="postgresql://postgres:DEMO@127.0.0.1:55439/postgres"),
            purpose="sql_write",
        )


def local_support():
    name = "tests.backend.local_supabase_live_support"
    assert find_spec(name), "Missing closed local receipt validation"
    return import_module(name)


def receipt_values():
    return {
        "project_id": "medithread-assistant-qa",
        "instance_nonce": "ee12bb02-4a76-473f-a2e7-335ff0f21dd3",
        "api_url": "http://127.0.0.1:55438",
        "database_host": "127.0.0.1",
        "database_port": 55439,
        "database_name": "postgres",
        "config_hash": "1" * 64,
        "cli_version": "3.0.0",
        "cli_hash": "81710c292b3defbfe05d990d46a56501c1be33528b0a113ff39531c2c8ee6de9",
        "image_digests": [
            {"name": name, "digest": "sha256:" + "2" * 64} for name in ("db", "auth", "rest", "storage", "gateway")
        ],
        "candidate_hashes": [{"name": "supabase/review/assistant_workflows/metadata.up.sql", "digest": "3" * 64}],
    }


def test_local_receipt_binds_exact_inventory_without_becoming_write_authority():
    s = local_support()
    receipt = s.LocalSupabaseTargetReceipt.model_validate_json(json.dumps(receipt_values()))
    s.validate_receipt_binding(
        receipt,
        config_hash="1" * 64,
        cli_hash="81710c292b3defbfe05d990d46a56501c1be33528b0a113ff39531c2c8ee6de9",
        candidate_hashes={"supabase/review/assistant_workflows/metadata.up.sql": "3" * 64},
    )
    with pytest.raises(ValueError):
        s.validate_receipt_binding(
            receipt,
            config_hash="0" * 64,
            cli_hash=receipt.cli_hash,
            candidate_hashes={"supabase/review/assistant_workflows/metadata.up.sql": "3" * 64},
        )
    with pytest.raises(ValueError):
        receipt.config_hash = "0" * 64


@pytest.mark.parametrize(
    "change",
    [
        {"project_id": "foreign-project"},
        {"instance_nonce": "00000000-0000-0000-0000-000000000000"},
        {"api_url": "http://localhost:55438"},
        {"api_url": "http://127.0.0.1:55438/"},
        {"api_url": "https://wteaeubvgmheqetmjbml.supabase.co"},
        {"api_url": "http://127.0.0.1:55438?target=other"},
        {"database_host": "localhost"},
        {"database_port": "55439"},
        {"database_port": 5432},
        {"database_name": "mt_assistant_test_demo"},
        {"config_hash": "not-a-hash"},
        {"cli_version": "latest"},
        {"cli_hash": "0" * 64},
        {"image_digests": []},
        {"candidate_hashes": []},
        {"admin_key": "DEMO_FORBIDDEN"},
    ],
)
def test_local_receipt_rejects_ambiguous_or_unpinned_identity_before_io(change, monkeypatch):
    s = local_support()

    def no_external_io(*args, **kwargs):
        pytest.fail("Receipt validation attempted external I/O")

    monkeypatch.setattr(httpx.Client, "request", no_external_io)
    monkeypatch.setattr(psycopg, "connect", no_external_io)
    monkeypatch.setattr(subprocess, "run", no_external_io)
    with pytest.raises(ValueError):
        s.LocalSupabaseTargetReceipt.model_validate_json(json.dumps(receipt_values() | change))


@pytest.mark.parametrize(
    "dsn,verifier",
    [
        ("postgresql://postgres:DEMO@127.0.0.1:55439/postgres", False),
        ("postgres://pharmascan_patient:DEMO@127.0.0.1:55439/postgres", False),
        ("postgresql://assistant_evidence_login:DEMO@127.0.0.1:55439/postgres", True),
        ("postgresql://assistant_evidence_login:DEMO@127.0.0.1:55439/postgres?sslmode=disable", True),
    ],
)
def test_local_sql_binding_accepts_only_explicit_loopback_and_expected_identity(dsn, verifier):
    s = local_support()
    assert callable(getattr(s, "validate_local_sql_dsn", None)), "Missing exact local SQL binding"
    s.validate_local_sql_dsn(dsn, verifier=verifier)


@pytest.mark.parametrize(
    "dsn,verifier",
    [
        ("postgresql://postgres:DEMO@localhost:55439/postgres", False),
        ("postgresql://postgres:DEMO@127.0.0.1:5432/postgres", False),
        ("postgresql://postgres:DEMO@127.0.0.1:055439/postgres", False),
        ("postgresql://postgres:DEMO@db.wteaeubvgmheqetmjbml.supabase.co/postgres", False),
        ("postgresql://postgres:DEMO@127.0.0.1:55439/mt_assistant_test_demo", False),
        ("postgresql://postgres:DEMO@127.0.0.1:55439/%70ostgres", False),
        ("postgresql://postgres@127.0.0.1:55439/postgres", False),
        ("postgresql://service_role:DEMO@127.0.0.1:55439/postgres", False),
        ("postgresql://assistant_evidence_login:DEMO@127.0.0.1:55439/postgres", False),
        ("postgresql://postgres:DEMO@127.0.0.1:55439/postgres?options=-crole=postgres", False),
        ("postgresql://postgres:DEMO@127.0.0.1:55439/postgres#fragment", False),
        ("postgresql://postgres:DEMO@127.0.0.1:55439/postgres", True),
        ("postgresql://assistant_evidence_login:DEMO@localhost:55439/postgres", True),
        ("postgresql://assistant_evidence_login:DEMO@127.0.0.1:55439/postgres?service=other", True),
        ("postgresql://assistant_evidence_login:DEMO@127.0.0.1:55439/postgres?host=other", True),
        ("postgresql://assistant_evidence_login:DEMO@127.0.0.1:55439/postgres?sslmode=disable&sslmode=disable", True),
    ],
)
def test_local_sql_binding_refuses_alternate_target_or_ambient_libpq_override(dsn, verifier, monkeypatch):
    s = local_support()
    assert callable(getattr(s, "validate_local_sql_dsn", None)), "Missing exact local SQL binding"

    def no_external_io(*args, **kwargs):
        pytest.fail("Rejected DSN attempted external I/O")

    monkeypatch.setattr(psycopg, "connect", no_external_io)
    monkeypatch.setattr(subprocess, "run", no_external_io)
    with pytest.raises(ValueError):
        s.validate_local_sql_dsn(dsn, verifier=verifier)


def local_profile_values():
    from uuid import UUID

    return values() | {
        "ASSISTANT_TEST_TARGET_MODE": "local_supabase",
        "ASSISTANT_TEST_LOCAL_RECEIPT_PATH": "DEMO_RECEIPT_PATH",
        "ASSISTANT_TEST_DATABASE_URL": "postgresql://postgres:DEMO@127.0.0.1:55439/postgres",
        "ASSISTANT_TEST_EVIDENCE_DSN": "postgresql://assistant_evidence_login:DEMO@127.0.0.1:55439/postgres",
        "ASSISTANT_TEST_SUPABASE_DATABASE_URL": "postgresql://postgres:DEMO@127.0.0.1:55439/postgres",
        "ASSISTANT_TEST_SUPABASE_URL": "http://127.0.0.1:55438",
        "ASSISTANT_TEST_PROJECT_REF": "medithread-assistant-qa",
        "ASSISTANT_TEST_PUBLISHABLE_KEY": "sb_publishable_DEMO",
        "ASSISTANT_TEST_JWT_A": jwt(UUID(int=1), issuer="http://127.0.0.1:55438/auth/v1"),
        "ASSISTANT_TEST_JWT_B": jwt(UUID(int=2), issuer="http://127.0.0.1:55438/auth/v1"),
    }


def test_local_mode_uses_bound_receipt_and_still_requires_independent_live_pairing(monkeypatch):
    from tests.backend.persistent_workflow_live_support import candidate_hashes

    s = local_support()
    receipt_data = receipt_values() | {
        "candidate_hashes": [{"name": p, "digest": h} for p, h in candidate_hashes().items()]
    }
    receipt = s.LocalSupabaseTargetReceipt.model_validate_json(json.dumps(receipt_data))
    monkeypatch.setattr(s, "read_bound_local_receipt", lambda profile: receipt, raising=False)
    profile = PersistentWorkflowTestProfile.from_values(
        local_profile_values() | {"ASSISTANT_TEST_CANDIDATE_HASHES": json.dumps(candidate_hashes())}
    )
    target = validate_persistent_test_profile(profile, purpose="sql_write", require_hashes=True)
    assert target.owner_a.int == 1 and target.owner_b.int == 2
    assert target.candidate_hashes == candidate_hashes()


@pytest.mark.parametrize(
    "change",
    [
        {"ASSISTANT_PERSISTENCE_APPROVED": "0"},
        {"ASSISTANT_TEST_DATABASE_URL": "postgresql://postgres:DEMO@127.0.0.1:5432/postgres"},
        {"ASSISTANT_TEST_EVIDENCE_DSN": "postgresql://postgres:DEMO@127.0.0.1:55439/postgres"},
        {"ASSISTANT_TEST_PROJECT_REF": "other-project"},
        {"ASSISTANT_TEST_SUPABASE_URL": "https://wteaeubvgmheqetmjbml.supabase.co"},
        {"ASSISTANT_TEST_OWNER_B": "00000000-0000-0000-0000-000000000001"},
        {"ASSISTANT_TEST_PUBLISHABLE_KEY": "sb_secret_DEMO"},
        {"ASSISTANT_TEST_CANDIDATE_HASHES": "{}"},
        {"ASSISTANT_TEST_SERVICE_ROLE_KEY": "DEMO_FORBIDDEN"},
    ],
)
def test_local_mode_refuses_invalid_profile_without_network_or_process(change, monkeypatch):
    from tests.backend.persistent_workflow_live_support import candidate_hashes

    s = local_support()
    receipt_data = receipt_values() | {
        "candidate_hashes": [{"name": p, "digest": h} for p, h in candidate_hashes().items()]
    }
    receipt = s.LocalSupabaseTargetReceipt.model_validate_json(json.dumps(receipt_data))
    monkeypatch.setattr(s, "read_bound_local_receipt", lambda profile: receipt, raising=False)

    def no_io(*args, **kwargs):
        pytest.fail("Invalid profile attempted network/process I/O")

    monkeypatch.setattr(psycopg, "connect", no_io)
    monkeypatch.setattr(httpx.Client, "request", no_io)
    monkeypatch.setattr(subprocess, "run", no_io)
    profile = PersistentWorkflowTestProfile.from_values(
        local_profile_values() | {"ASSISTANT_TEST_CANDIDATE_HASHES": json.dumps(candidate_hashes())} | change
    )
    with pytest.raises(PersistentProfileRefusal):
        validate_persistent_test_profile(profile, purpose="sql_write", require_hashes=True)


def runtime_snapshot():
    receipt = local_support().LocalSupabaseTargetReceipt.model_validate_json(json.dumps(receipt_values()))
    ownership = {
        "network_id": "a" * 64,
        "network_name": "medithread-assistant-qa-local",
        "image_pins": {
            name: {"config_digest": "sha256:" + "2" * 64}
            for name in ("db", "auth", "rest", "storage", "gateway")
        },
    }
    network = {
        "Id": "a" * 64,
        "Name": ownership["network_name"],
        "Driver": "bridge",
        "Labels": {
            "com.medithread.acceptance.project": receipt.project_id,
            "com.medithread.acceptance.instance": str(receipt.instance_nonce),
        },
        "Options": {"com.docker.network.bridge.host_binding_ipv4": "127.0.0.1"},
    }
    prefixes = {"db": "db", "auth": "auth", "rest": "rest", "storage": "storage", "gateway": "kong"}
    containers = {}
    for i, (service, prefix) in enumerate(prefixes.items()):
        ports = {}
        if service in {"db", "gateway"}:
            ports = {
                ("5432/tcp" if service == "db" else "8000/tcp"): [
                    {"HostIp": "127.0.0.1", "HostPort": "55439" if service == "db" else "55438"}
                ]
            }
        containers[service] = {
            "Id": "b" * 63 + str(i),
            "Name": f"/supabase_{prefix}_{receipt.project_id}",
            "Image": "sha256:" + "2" * 64,
            "Config": {"Labels": {"com.supabase.cli.project": receipt.project_id}},
            "State": {"Running": True, "Health": {"Status": "healthy"}},
            "NetworkSettings": {"Networks": {ownership["network_name"]: {"NetworkID": "a" * 64}}, "Ports": ports},
        }
    return receipt, ownership, network, containers


def test_local_runtime_requires_owned_network_and_loopback_only_publications():
    s = local_support()
    assert callable(getattr(s, "validate_runtime_snapshot", None)), "Missing runtime ownership verification"
    s.validate_runtime_snapshot(*runtime_snapshot())


@pytest.mark.parametrize(
    "fault",
    [
        "foreign_nonce",
        "network_public",
        "public_port",
        "foreign_label",
        "wrong_image",
        "foreign_network",
        "stopped",
        "missing",
    ],
)
def test_local_runtime_refuses_confusable_or_publicly_exposed_stack(fault):
    s = local_support()
    assert callable(getattr(s, "validate_runtime_snapshot", None)), "Missing runtime ownership verification"
    receipt, ownership, network, containers = copy.deepcopy(runtime_snapshot())
    if fault == "foreign_nonce":
        network["Labels"]["com.medithread.acceptance.instance"] = "other"
    elif fault == "network_public":
        network["Options"]["com.docker.network.bridge.host_binding_ipv4"] = "0.0.0.0"
    elif fault == "public_port":
        containers["db"]["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostIp"] = "::"
    elif fault == "foreign_label":
        containers["auth"]["Config"]["Labels"]["com.supabase.cli.project"] = "other"
    elif fault == "wrong_image":
        containers["auth"]["Image"] = "sha256:" + "0" * 64
    elif fault == "foreign_network":
        containers["db"]["NetworkSettings"]["Networks"][ownership["network_name"]]["NetworkID"] = "other"
    elif fault == "stopped":
        containers["db"]["State"]["Running"] = False
    elif fault == "missing":
        del containers["storage"]
    with pytest.raises(ValueError):
        s.validate_runtime_snapshot(receipt, ownership, network, containers)


@pytest.mark.parametrize("fault", [None, "redirect", "wrong_auth_owner", "wrong_api_nonce", "wrong_api_owner"])
def test_auth_and_data_pairing_rejects_redirects_and_different_datasets(fault):
    from uuid import UUID

    from tests.backend.persistent_workflow_live_support import ApprovedTestTarget

    s = local_support()
    assert callable(getattr(s, "verify_auth_data_pairing", None)), "Missing real Auth/Data API pairing"
    profile = PersistentWorkflowTestProfile.from_values(local_profile_values())
    target = ApprovedTestTarget("0" * 64, UUID(int=1), UUID(int=2), {})
    rows = [(str(UUID(int=i)), "ee12bb02-4a76-473f-a2e7-335ff0f21dd3", str(UUID(int=i + 10))) for i in (1, 2)]
    writes = []

    def handler(request):
        if request.method != "GET":
            writes.append(request.method)
        is_a = request.headers["Authorization"].endswith(profile.storage_values["ASSISTANT_TEST_JWT_A"])
        row = rows[0 if is_a else 1]
        if request.url.path == "/auth/v1/user":
            if fault == "redirect":
                return httpx.Response(302, headers={"location": "https://example.invalid"})
            return httpx.Response(
                200, json={"id": str(UUID(int=99)) if fault == "wrong_auth_owner" else row[0], "role": "authenticated"}
            )
        assert request.url.path == "/rest/v1/medithread_local_acceptance"
        return httpx.Response(
            200,
            json=[
                {
                    "owner": str(UUID(int=99)) if fault == "wrong_api_owner" else row[0],
                    "instance_nonce": row[1],
                    "challenge": str(UUID(int=99)) if fault == "wrong_api_nonce" else row[2],
                    "demo_only": True,
                }
            ],
        )

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False, trust_env=False) as client:
        if fault is None:
            s.verify_auth_data_pairing(profile, target, rows, http=client)
        else:
            with pytest.raises(ValueError):
                s.verify_auth_data_pairing(profile, target, rows, http=client)
    assert not writes


def local_runner():
    name = "scripts.qa.local_supabase_acceptance"
    assert find_spec(name), "Missing explicit local acceptance runner"
    return import_module(name)


def test_local_runner_default_is_read_only_and_refuses_unapproved_actions(monkeypatch, tmp_path, capsys):
    s = local_runner()
    monkeypatch.setattr(s, "WORKDIR", tmp_path)

    def no_io(*args, **kwargs):
        pytest.fail("Unapproved/default command performed external I/O")

    monkeypatch.setattr(subprocess, "run", no_io)
    monkeypatch.setattr(psycopg, "connect", no_io)
    monkeypatch.setattr(httpx.Client, "request", no_io)
    assert s.main([]) == 2
    assert json.loads(capsys.readouterr().out)["real_services"] == "NOT_CHECKED"
    for stage in ("start", "bootstrap", "accept", "serve", "stop"):
        assert s.main([stage]) == 2
        result = json.loads(capsys.readouterr().out)
        assert result["reason"] == "explicit_local_approval_required"
    assert not list(tmp_path.iterdir())


def test_local_environment_discards_ambient_credentials_and_redirectors(monkeypatch):
    s = local_runner()
    for key in ("PGHOST", "PGSERVICE", "PGPASSWORD", "SUPABASE_ACCESS_TOKEN", "GEMINI_API_KEY", "HTTP_PROXY"):
        monkeypatch.setenv(key, "DEMO_FORBIDDEN")
    env = s.local_environment()
    assert not any(value == "DEMO_FORBIDDEN" for value in env.values())
    assert env["DOCKER_HOST"] == s.DOCKER_COMMAND[2]
    assert env["SUPABASE_TELEMETRY_DISABLED"] == "1"


def test_local_accept_records_interruption_without_claiming_not_run(monkeypatch, tmp_path, capsys):
    s = local_runner()
    monkeypatch.setattr(s, "WORKDIR", tmp_path)
    (tmp_path / "profile.json").write_text(
        json.dumps({"ASSISTANT_PERSISTENCE_APPROVAL_ID": "DEMO_LOCAL", "ASSISTANT_TEST_TARGET_MODE": "local_supabase"})
    )
    monkeypatch.setattr(s, "validate_persistent_test_profile", lambda *a, **k: None)

    def interrupted(*args, **kwargs):
        raise subprocess.TimeoutExpired("DEMO", 1)

    monkeypatch.setattr(subprocess, "run", interrupted)
    assert s.main(["accept", "--approval-id", "DEMO_LOCAL"]) != 0
    result = json.loads(capsys.readouterr().out)
    assert result["real_acceptance"] == "INTERRUPTED"
    assert result["evidence"]


def test_local_accept_rejects_profile_environment_injection_before_child_process(monkeypatch, tmp_path, capsys):
    s = local_runner()
    monkeypatch.setattr(s, "WORKDIR", tmp_path)
    (tmp_path / "profile.json").write_text(
        json.dumps({"ASSISTANT_PERSISTENCE_APPROVAL_ID": "DEMO_LOCAL", "PYTEST_ADDOPTS": "--DEMO_FORBIDDEN"})
    )
    monkeypatch.setattr(s, "validate_persistent_test_profile", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    assert s.main(["accept", "--approval-id", "DEMO_LOCAL"]) == 2
    assert not calls
    assert json.loads(capsys.readouterr().out)["real_acceptance"] == "NOT_RUN"


def test_runtime_rejects_recreated_same_name_container_even_with_same_image():
    s = local_support()
    receipt, ownership, network, containers = runtime_snapshot()
    ownership["container_ids"] = {name: c["Id"] for name, c in containers.items()}
    containers["auth"]["Id"] = "c" * 64
    with pytest.raises(ValueError):
        s.validate_runtime_snapshot(receipt, ownership, network, containers)


def test_runtime_cannot_bless_unpinned_image_by_copying_it_into_a_new_receipt():
    s = local_support()
    receipt, ownership, network, containers = runtime_snapshot()
    data = receipt.model_dump(mode="json")
    data["image_digests"][0]["digest"] = "sha256:" + "f" * 64
    containers[data["image_digests"][0]["name"]]["Image"] = "sha256:" + "f" * 64
    receipt = s.LocalSupabaseTargetReceipt.model_validate_json(json.dumps(data))
    with pytest.raises(ValueError):
        s.validate_runtime_snapshot(receipt, ownership, network, containers)


def test_live_admission_checks_runtime_before_any_sql_or_http(monkeypatch):
    s = local_support()
    core = import_module("tests.backend.persistent_workflow_live_support")
    receipt = s.LocalSupabaseTargetReceipt.model_validate_json(json.dumps(receipt_values()))
    target = core.ApprovedTestTarget("DEMO", receipt.instance_nonce, receipt.instance_nonce, {})
    monkeypatch.setattr(core, "validate_persistent_test_profile", lambda *a, **k: target)
    monkeypatch.setattr(s, "read_bound_local_receipt", lambda profile: receipt)

    def wrong_runtime(*args):
        raise ValueError("DEMO_FOREIGN_CONTAINER")

    def forbidden_connection(*args, **kwargs):
        pytest.fail("Unowned runtime attempted SQL or HTTP access")

    monkeypatch.setattr(s, "inspect_owned_runtime", wrong_runtime)
    monkeypatch.setattr(psycopg, "connect", forbidden_connection)
    monkeypatch.setattr(httpx.Client, "request", forbidden_connection)
    with pytest.raises(PersistentProfileRefusal):
        s.verify_local_live_target(PersistentWorkflowTestProfile(), target)


def test_source_plan_keeps_raw_receipt_and_canonical_ledger_hashes_distinct(monkeypatch, tmp_path):
    import hashlib

    s = local_runner()
    monkeypatch.setattr(s, "ROOT", tmp_path)
    work = tmp_path / "private"
    work.mkdir()
    monkeypatch.setattr(s, "WORKDIR", work)
    directory = tmp_path / "supabase/migrations"
    directory.mkdir(parents=True)
    hashes = {}
    for i in range(50):
        path = directory / f"{i:03d}_demo.sql"
        path.write_bytes(b"BEGIN;\r\nSELECT 1;\r\nCOMMIT;\r\n")
        hashes[path.relative_to(tmp_path).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    inventory = {
        "project_id": "medithread-assistant-qa",
        "down_execution_authorized": False,
        "source_hashes": hashes,
        "planned_apply_order": list(hashes),
    }
    (work / "source-inventory.json").write_text(json.dumps(inventory))
    plan = s.source_plan()
    assert len(plan) == 50
    assert plan[0].sha256 == hashlib.sha256(b"BEGIN;\nSELECT 1;\nCOMMIT;\n").hexdigest()
    assert plan[0].sha256 != next(iter(hashes.values()))
    plan[0].path.write_bytes(b"SELECT 'DEMO_CHANGED';")
    with pytest.raises(ValueError):
        s.source_plan()


def test_unapproved_down_probe_skips_before_requesting_live_fixture(monkeypatch):
    from types import SimpleNamespace

    from tests.backend.test_persistent_workflow_sql_live import (
        test_live_nonempty_down_guard_refuses_without_executing_drop as probe,
    )

    monkeypatch.delenv("ASSISTANT_PERSISTENCE_DOWN_APPROVED", raising=False)
    monkeypatch.setenv("RUN_ASSISTANT_PERSISTENCE_TESTS", "1")

    def no_fixture(*args):
        pytest.fail("Unapproved down probe requested a connecting fixture")

    with pytest.raises(pytest.skip.Exception):
        probe(SimpleNamespace(getfixturevalue=no_fixture))


def test_start_rejects_changed_cli_before_invoking_it(monkeypatch, tmp_path, capsys):
    s = local_runner()
    monkeypatch.setattr(s, "WORKDIR", tmp_path)
    cli = tmp_path / "supabase.exe"
    cli.write_bytes(b"DEMO_CHANGED_EXECUTABLE")
    monkeypatch.setattr(s, "CLI", cli)
    (tmp_path / "supabase").mkdir()
    (tmp_path / "supabase/config.toml").write_text("DEMO_CONFIG")
    ownership = {
        "project_id": "medithread-assistant-qa",
        "network_id": "DEMO",
        "network_name": "DEMO",
        "instance_nonce": "DEMO",
    }
    (tmp_path / "runtime-owner.json").write_text(json.dumps(ownership))
    monkeypatch.setattr(s, "docker_inspect", lambda *a: {"Labels": {"com.medithread.acceptance.instance": "DEMO"}})
    calls = []

    def invoked(*args, **kwargs):
        calls.append(args)
        raise ValueError("DEMO_COMMAND_INVOKED")

    monkeypatch.setattr(s, "invoke", invoked)
    assert s.main(["start", "--approval-id", "DEMO_LOCAL"]) == 2
    assert not calls
    assert json.loads(capsys.readouterr().out)["real_acceptance"] == "NOT_RUN"


def test_real_service_runtime_refuses_default_before_external_io(monkeypatch):
    name = "tests.backend.local_supabase_runtime"
    assert find_spec(name), "Missing isolated real-service runtime"
    runtime = import_module(name)
    monkeypatch.delenv("MEDITHREAD_LOCAL_ACCEPTANCE", raising=False)

    def no_io(*args, **kwargs):
        pytest.fail("Unapproved runtime attempted external I/O")

    monkeypatch.setattr(psycopg, "connect", no_io)
    monkeypatch.setattr(subprocess, "run", no_io)
    monkeypatch.setattr(httpx.Client, "request", no_io)
    with pytest.raises(RuntimeError, match="explicit local"):
        runtime.create_app()


@pytest.mark.parametrize("second_start_fails", [False, True])
def test_unified_local_servers_use_loopback_public_frontend_config_and_owned_cleanup(
    monkeypatch, tmp_path, second_start_fails
):
    from types import SimpleNamespace

    from scripts import start_dev

    s = local_runner()
    monkeypatch.setattr(s, "ROOT", tmp_path)
    (tmp_path / "frontend/node_modules/.bin").mkdir(parents=True)
    (tmp_path / "frontend/node_modules/.bin/vite").touch()
    monkeypatch.setattr(s, "validate_persistent_test_profile", lambda *a, **k: None)
    monkeypatch.setattr(local_support(), "verify_local_live_target", lambda *a: None)
    monkeypatch.setattr(s.shutil, "which", lambda name: "D:/DEMO/tools/" + name)
    ports, started, stopped = [], [], []
    monkeypatch.setattr(start_dev, "check_port", ports.append)

    def start(command, cwd, env):
        if second_start_fails and started:
            raise OSError("DEMO second process unavailable")
        process = SimpleNamespace(poll=lambda: None)
        started.append((command, cwd, env, process))
        return process

    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(start_dev, "start_process", start)
    monkeypatch.setattr(start_dev, "stop_process", stopped.append)
    monkeypatch.setattr(s.time, "sleep", interrupt)
    profile = PersistentWorkflowTestProfile.from_values(local_profile_values())
    if second_start_fails:
        with pytest.raises(OSError):
            s.serve(profile)
    else:
        assert s.serve(profile)["status"] == "APP_STOPPED"
        assert started[1][2]["VITE_SUPABASE_URL"] == "http://127.0.0.1:55438"
        assert started[1][2]["VITE_API_TARGET"] == "http://127.0.0.1:8027"
    assert ports == [8027, 5195]
    assert stopped == [record[3] for record in reversed(started)]
    for command, _, env, _ in started:
        assert command[command.index("--host") + 1] == "127.0.0.1"
        assert not any(key.startswith("ASSISTANT_TEST_") for key in env)
        assert "DATABASE_URL" not in env and "SUPABASE_SECRET_KEY" not in env
