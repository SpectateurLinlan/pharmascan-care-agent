"""DEMO_ONLY offline admission checks; none grants permission for real execution."""

import base64
import json
from dataclasses import replace
from uuid import UUID

import pytest


def support():
    from importlib import import_module
    from importlib.util import find_spec

    assert find_spec("tests.backend.persistent_workflow_live_support"), "Missing explicit persistent acceptance profile"
    return import_module("tests.backend.persistent_workflow_live_support")


def values():
    return {
        "RUN_ASSISTANT_PERSISTENCE_TESTS": "1",
        "RUN_ASSISTANT_SQL_TESTS": "1",
        "ASSISTANT_PERSISTENCE_APPROVED": "1",
        "ASSISTANT_PERSISTENCE_OPERATIONS": "sql_read,sql_write",
        "ASSISTANT_PERSISTENCE_APPROVAL_ID": "DEMO-ONLY-APPROVAL",
        "ASSISTANT_TEST_DATABASE_URL": "postgresql://postgres:DEMO@127.0.0.1:55439/mt_assistant_test_demo",
        "ASSISTANT_TEST_EVIDENCE_DSN": "postgresql://assistant_evidence_login:DEMO@127.0.0.1:55439/mt_assistant_test_demo",
        "ASSISTANT_TEST_OWNER_A": "00000000-0000-0000-0000-000000000001",
        "ASSISTANT_TEST_OWNER_B": "00000000-0000-0000-0000-000000000002",
    }


@pytest.mark.parametrize(
    "change",
    [
        {"RUN_ASSISTANT_PERSISTENCE_TESTS": "0"},
        {"RUN_ASSISTANT_SQL_TESTS": "0"},
        {"ASSISTANT_PERSISTENCE_APPROVED": "0"},
        {"ASSISTANT_PERSISTENCE_APPROVAL_ID": ""},
        {"ASSISTANT_TEST_DATABASE_URL": "postgresql://postgres:DEMO@db.normal.supabase.co/postgres"},
        {"ASSISTANT_TEST_DATABASE_URL": "postgresql://postgres:DEMO@127.0.0.1:5432/mt_assistant_test_demo"},
        {"ASSISTANT_TEST_DATABASE_URL": "postgresql://postgres:DEMO@127.0.0.1:55439/postgres"},
        {
            "ASSISTANT_TEST_DATABASE_URL": "postgresql://postgres:DEMO@127.0.0.1:55439/mt_assistant_test_demo?options=bad"
        },
        {"ASSISTANT_TEST_OWNER_B": "00000000-0000-0000-0000-000000000001"},
        {"ASSISTANT_TEST_OWNER_A": ""},
        {"ASSISTANT_TEST_OWNER_A": "00000000-0000-0000-0000-000000000000"},
        {"ASSISTANT_PERSISTENCE_OPERATIONS": "sql_read,sql_write,apply_sql"},
        {"ASSISTANT_PERSISTENCE_OPERATIONS": "sql_read,sql_write,storage_policies"},
        {"ASSISTANT_TEST_SERVICE_ROLE_KEY": "DEMO-FORBIDDEN"},
    ],
)
def test_persistence_profile_rejects_unapproved_target_without_io(change, monkeypatch):
    import socket

    import httpx
    import psycopg

    s = support()

    def no_io(*a, **k):
        pytest.fail("Admission attempted external I/O")

    monkeypatch.setattr(socket, "create_connection", no_io)
    monkeypatch.setattr(psycopg, "connect", no_io)
    monkeypatch.setattr(httpx.Client, "request", no_io)
    profile = s.PersistentWorkflowTestProfile.from_values(values() | change)
    with pytest.raises(s.PersistentProfileRefusal) as refusal:
        s.validate_persistent_test_profile(profile, purpose="sql_write")
    assert refusal.value.code == "target_not_authorized"
    assert "DEMO-FORBIDDEN" not in str(refusal.value)


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://assistant_evidence_login:DEMO@127.0.0.1:55439/mt_assistant_test_other",
        "postgresql://assistant_evidence_login:DEMO@127.0.0.1:55440/mt_assistant_test_demo",
        "postgresql://postgres:DEMO@127.0.0.1:55439/mt_assistant_test_demo",
        "postgresql://authenticated:DEMO@127.0.0.1:55439/mt_assistant_test_demo",
        "postgresql://assistant_evidence_login:DEMO@localhost:55439/mt_assistant_test_demo",
        "postgresql://assistant_evidence_login:DEMO@127.0.0.1:55439/mt_assistant_test_demo?options=bad",
    ],
)
def test_persistence_evidence_dsn_must_match_isolated_database(dsn):
    s = support()
    profile = s.PersistentWorkflowTestProfile.from_values(values() | {"ASSISTANT_TEST_EVIDENCE_DSN": dsn})
    with pytest.raises(s.PersistentProfileRefusal):
        s.validate_persistent_test_profile(profile, purpose="sql_write")


def test_persistence_profile_has_stable_target_and_exact_source_hashes_without_credentials():
    s = support()
    profile = s.PersistentWorkflowTestProfile.from_values(values())
    target = s.validate_persistent_test_profile(profile, purpose="sql_write")
    assert target.owner_a != target.owner_b and target.owner_a == UUID(int=1)
    assert len(target.database_fingerprint) == 64
    assert len(target.candidate_hashes) >= 23
    assert all(len(h) == 64 for h in target.candidate_hashes.values())
    assert "postgresql://" not in repr(profile) and ":DEMO@" not in repr(target)
    assert s.validate_persistent_test_profile(profile, purpose="sql_write") == target


def test_persistence_approval_requires_current_candidate_hash_manifest():
    s = support()
    profile = s.PersistentWorkflowTestProfile.from_values(values())
    with pytest.raises(s.PersistentProfileRefusal):
        s.validate_persistent_test_profile(profile, purpose="sql_write", require_hashes=True)
    hashes = s.candidate_hashes()
    profile = s.PersistentWorkflowTestProfile.from_values(
        values() | {"ASSISTANT_TEST_CANDIDATE_HASHES": json.dumps(hashes)}
    )
    assert s.validate_persistent_test_profile(profile, purpose="sql_write", require_hashes=True)
    hashes[next(iter(hashes))] = "0" * 64
    with pytest.raises(s.PersistentProfileRefusal):
        s.validate_persistent_test_profile(
            replace(profile, approved_candidate_hashes=hashes), purpose="sql_write", require_hashes=True
        )


def test_persistence_inspection_does_not_grant_write_or_down_scope():
    s = support()
    profile = s.PersistentWorkflowTestProfile.from_values(
        values() | {"RUN_ASSISTANT_SQL_TESTS": "0", "ASSISTANT_PERSISTENCE_OPERATIONS": "sql_read"}
    )
    assert s.validate_persistent_test_profile(profile, purpose="sql_read")
    for purpose in ["sql_write", "storage_read", "storage_write", "down_probe", "apply_sql", "notification_send"]:
        with pytest.raises(s.PersistentProfileRefusal):
            s.validate_persistent_test_profile(profile, purpose=purpose)


def jwt(owner, issuer="https://demoisolated.supabase.co/auth/v1", role="authenticated"):
    body = (
        base64.urlsafe_b64encode(
            json.dumps({"sub": str(owner), "iss": issuer, "role": role, "exp": 4102444800}).encode()
        )
        .decode()
        .rstrip("=")
    )
    return "DEMO." + body + ".DEMO"


def storage_values():
    v = values() | {
        "ASSISTANT_PERSISTENCE_OPERATIONS": "storage_read,storage_write",
        "RUN_ASSISTANT_STORAGE_TESTS": "1",
        "ASSISTANT_TEST_PROJECT_REF": "demoisolated",
        "ASSISTANT_TEST_SUPABASE_URL": "https://demoisolated.supabase.co",
        "ASSISTANT_NORMAL_SUPABASE_URL": "https://demonormal.supabase.co",
        "ASSISTANT_TEST_SUPABASE_DATABASE_URL": "postgresql://postgres@db.demoisolated.supabase.co/postgres",
        "ASSISTANT_TEST_PUBLISHABLE_KEY": "sb_publishable_DEMO",
    }
    v["ASSISTANT_TEST_JWT_A"] = jwt(UUID(int=1))
    v["ASSISTANT_TEST_JWT_B"] = jwt(UUID(int=2))
    return v


@pytest.mark.parametrize(
    "change",
    [
        {"ASSISTANT_NORMAL_SUPABASE_URL": ""},
        {"ASSISTANT_NORMAL_SUPABASE_URL": "https://demoisolated.supabase.co"},
        {"ASSISTANT_TEST_SUPABASE_URL": "https://evil.invalid"},
        {"ASSISTANT_TEST_JWT_A": jwt(UUID(int=2))},
        {"ASSISTANT_TEST_JWT_A": jwt(UUID(int=1), role="service_role")},
        {"ASSISTANT_TEST_JWT_A": jwt(UUID(int=1), issuer="https://demonormal.supabase.co/auth/v1")},
        {"ASSISTANT_TEST_PUBLISHABLE_KEY": "sb_secret_DEMO"},
        {"RUN_ASSISTANT_STORAGE_TESTS": "0"},
    ],
)
def test_persistence_storage_requires_original_guard_and_bound_patient_claims(change):
    s = support()
    profile = s.PersistentWorkflowTestProfile.from_values(storage_values() | change)
    with pytest.raises(s.PersistentProfileRefusal):
        s.validate_persistent_test_profile(profile, purpose="storage_write")


def test_persistence_storage_offline_claims_are_not_real_auth_acceptance():
    s = support()
    profile = s.PersistentWorkflowTestProfile.from_values(storage_values())
    assert s.validate_persistent_test_profile(profile, purpose="storage_write")
    assert "DEMO." not in repr(profile)
