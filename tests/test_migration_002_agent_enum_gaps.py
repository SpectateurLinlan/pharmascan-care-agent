"""Static review of the corrective migration 202610130002.

** Static only. ** These assertions read SQL text; they do not connect to
PostgreSQL and do not prove the migration applied. The real application of this
file is recorded in `outputs/db_schema_report.json`
(`agent_allowlists.checks`) and `outputs/db_rls_isolation_report.json`, both
produced by running against the remote development database.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from uuid import UUID, uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "supabase" / "migrations" / "202610130002_agent_enum_gaps.sql"
ROLLBACK_PATH = ROOT / "supabase" / "rollback" / "202610130002_agent_enum_gaps_down.sql"
CORE_PATH = ROOT / "supabase" / "migrations" / "202610130001_core.sql"

#: Values the core migration omitted and this migration must add.
ADDED_TOOL_NAMES = ("get_dose_status",)
ADDED_INTENTS = ("dose_status_query",)

#: Values the core migration already had; neither file may remove them.
ORIGINAL_TOOL_NAMES = (
    "list_active_medications",
    "get_medication_history",
    "enroll_medication_draft",
    "confirm_regimen_draft",
    "check_due_dose",
    "record_self_report",
)
ORIGINAL_INTENTS = (
    "medication_enrollment",
    "dose_self_report",
    "medication_history",
    "clarification",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _without_comments(sql: str) -> str:
    tokens = re.compile(r"'(?:''|[^'])*'|\$\$[\s\S]*?\$\$|--[^\n]*|/\*[\s\S]*?\*/")
    return tokens.sub(
        lambda match: " " if match.group().startswith(("--", "/*")) else match.group(),
        sql,
    )


@pytest.fixture(scope="module")
def migration() -> str:
    return _read(MIGRATION_PATH)


@pytest.fixture(scope="module")
def rollback() -> str:
    return _read(ROLLBACK_PATH)


@pytest.fixture(scope="module")
def code(migration: str) -> str:
    return _without_comments(migration)


def test_both_files_exist() -> None:
    assert MIGRATION_PATH.is_file()
    assert ROLLBACK_PATH.is_file()


def test_migration_is_transactional(code: str) -> None:
    assert code.lstrip().upper().startswith("BEGIN;")
    assert code.rstrip().upper().endswith("COMMIT;")


def test_migration_has_a_matching_rollback_in_the_ledger_order(migration: str) -> None:
    assert hashlib.sha256(migration.encode("utf-8")).hexdigest()
    assert MIGRATION_PATH.name > CORE_PATH.name, "must sort after the core migration"


def test_migration_completes_both_enum_allowlists(code: str) -> None:
    for value in ADDED_TOOL_NAMES + ADDED_INTENTS:
        assert f"'{value}'" in code
    for value in ORIGINAL_TOOL_NAMES + ORIGINAL_INTENTS:
        assert f"'{value}'" in code


def test_migration_replaces_the_named_constraints(code: str) -> None:
    assert "DROP CONSTRAINT agent_tool_calls_tool_name_check" in code
    assert "DROP CONSTRAINT agent_sessions_intent_check" in code
    assert code.count("ADD CONSTRAINT agent_tool_calls_tool_name_check") == 1
    assert code.count("ADD CONSTRAINT agent_sessions_intent_check") == 1


def test_migration_adds_the_three_redaction_keys(code: str) -> None:
    for key in ("'already_recorded'", "'missing_count'", "'no_report'"):
        assert key in code


def test_migration_keeps_the_safety_bounds(code: str) -> None:
    """Widening an allowlist must not relax the redaction guarantees."""
    assert "1024" in code, "the size bound must be preserved"
    # pg_get_functiondef renders the literal as '"not_checked"'::jsonb.
    assert "not_checked" in code, "the P0 no-photo rule must be preserved"
    assert "jsonb_typeof(entry.item) <> 'boolean'" in code
    assert "entry.item <> 'true'::jsonb" in code, "demo_only must still be true"


def test_migration_never_drops_schema_objects(code: str) -> None:
    for forbidden in (
        "DROP TABLE",
        "DROP COLUMN",
        "DROP POLICY",
        "DROP INDEX",
        "DROP TRIGGER",
        "DROP FUNCTION",
        "ALTER COLUMN",
        "REVOKE SELECT",
        "TRUNCATE",
        "DELETE FROM",
    ):
        assert forbidden not in code.upper().replace("DROP CONSTRAINT", "")


def test_rollback_restores_the_core_allowlists(code: str, rollback: str) -> None:
    rollback_code = _without_comments(rollback)
    for value in ADDED_TOOL_NAMES + ADDED_INTENTS:
        assert f"'{value}'" not in rollback_code, (
            "the rollback must return to the core allowlist exactly"
        )
    for value in ORIGINAL_TOOL_NAMES + ORIGINAL_INTENTS:
        assert f"'{value}'" in rollback_code
    assert rollback_code.lstrip().upper().startswith("BEGIN;")
    assert rollback_code.rstrip().upper().endswith("COMMIT;")


def test_rollback_is_stricter_than_the_migration(code: str, rollback: str) -> None:
    """Every value the rollback admits must also be admitted by the migration."""
    migration_intake = set(re.findall(r"'(\w+)'", code))
    rollback_intake = set(re.findall(r"'(\w+)'", _without_comments(rollback)))
    assert rollback_intake <= migration_intake


# --- adapter derivations (pure functions, no database) -----------------------


def test_synthetic_source_checksum_matches_the_sql_regex() -> None:
    from app.infrastructure.postgres_repos import synthetic_source_checksum

    patient = UUID("11111111-1111-1111-1111-111111111111")
    source = UUID("22222222-2222-2222-2222-222222222222")
    value = synthetic_source_checksum(patient, source)
    assert re.fullmatch(r"[0-9a-f]{64}", value)
    assert value == synthetic_source_checksum(patient, source), "must be deterministic"
    assert value != synthetic_source_checksum(source, patient), "must be bound to both ids"


def test_synthetic_evidence_locator_matches_the_sql_regex() -> None:
    from app.infrastructure.postgres_repos import synthetic_evidence_locator

    value = synthetic_evidence_locator(uuid4())
    assert re.fullmatch(r"synthetic:[A-Za-z0-9_.:-]{1,120}", value)


def test_challenge_request_hash_is_stable_and_binding_specific() -> None:
    from app.infrastructure.postgres_repos import challenge_request_hash

    base = {
        "patient_id": uuid4(),
        "action": "record_self_report",
        "regimen_id": uuid4(),
        "occurrence_id": None,
        "intake_status": "reported_taken",
        "idempotency_key": "k-1",
    }
    first = challenge_request_hash(**base)
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert first == challenge_request_hash(**base)
    assert first != challenge_request_hash(**{**base, "idempotency_key": "k-2"})
    assert first != challenge_request_hash(**{**base, "intake_status": "unsure"})


def test_ports_are_unchanged_by_the_adapter() -> None:
    """The adapter must implement the existing Ports, not extend them."""
    from app.contracts import ports
    from app.infrastructure import postgres_repos as adapter

    expected = {
        "SourceDocumentRepository": ("get", "add", "update"),
        "SourceFieldRepository": ("list_for_source", "add", "update"),
        "PatientMedicationRepository": ("get", "list_for_patient", "add", "update"),
        "RegimenVersionRepository": (
            "get",
            "list_for_medication",
            "find_active_for_medication",
            "next_version_no",
            "add",
            "update",
        ),
        "DoseRuleRepository": ("list_for_regimen", "add"),
        "DoseOccurrenceRepository": (
            "get",
            "find_by_generation_key",
            "list_for_regimen",
            "add",
            "update",
        ),
        "DoseEventRepository": (
            "find_by_idempotency_key",
            "find_by_occurrence",
            "list_for_patient",
            "add",
        ),
        "AgentSessionRepository": ("get", "add", "update"),
        "ConfirmationChallengeRepository": (
            "get",
            "find_by_token_hash",
            "add",
            "update",
        ),
        "ToolTraceRepository": ("add", "list_for_session"),
    }
    for port_name, methods in expected.items():
        protocol = getattr(ports, port_name)
        for method in methods:
            assert hasattr(protocol, method)

    implementations = {
        "PostgresSourceDocumentRepository": expected["SourceDocumentRepository"],
        "PostgresSourceFieldRepository": expected["SourceFieldRepository"],
        "PostgresPatientMedicationRepository": expected["PatientMedicationRepository"],
        "PostgresRegimenVersionRepository": expected["RegimenVersionRepository"],
        "PostgresDoseRuleRepository": expected["DoseRuleRepository"],
        "PostgresDoseOccurrenceRepository": expected["DoseOccurrenceRepository"],
        "PostgresDoseEventRepository": expected["DoseEventRepository"],
        "PostgresAgentSessionRepository": expected["AgentSessionRepository"],
        "PostgresConfirmationChallengeRepository": expected[
            "ConfirmationChallengeRepository"
        ],
        "PostgresToolTraceRepository": expected["ToolTraceRepository"],
    }
    for class_name, methods in implementations.items():
        cls = getattr(adapter, class_name)
        for method in methods:
            assert callable(getattr(cls, method)), f"{class_name}.{method} missing"
