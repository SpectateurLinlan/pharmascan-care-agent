"""Offline review guards, not PostgreSQL/RLS execution evidence."""

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "supabase/review/assistant_workflows"


def candidate(name):
    path = REVIEW / name
    assert path.is_file(), f"Missing reviewed persistence candidate: {name}"
    return path.read_text(encoding="utf-8")


def test_candidates_revoke_public_and_have_empty_only_down():
    up, down = candidate("metadata.up.sql"), candidate("metadata.down.sql")
    assert "REVOKE ALL" in up and "FROM PUBLIC" in up
    assert "FORCE ROW LEVEL SECURITY" in up
    assert "SET search_path=''" in up
    assert "session_user" in up and "assistant_evidence_login" in up
    assert "nonempty" in down.lower() and down.index("RAISE EXCEPTION") < down.index("DROP")
    assert not re.search(r"\b(?:DELETE\s+FROM|TRUNCATE|CASCADE)\b", down, re.I)


def test_evidence_owner_is_separate_from_business_receipts_and_clinical_tables():
    text = candidate("metadata.up.sql")
    for table in [
        "assistant_storage_tickets",
        "assistant_verified_operations",
        "assistant_runtime_runs",
        "assistant_runtime_events",
        "assistant_business_receipts",
    ]:
        assert f"CREATE TABLE public.{table}" in text
    assert "ALTER TABLE public.assistant_business_receipts OWNER TO assistant_workflow_owner" in text
    assert "ALTER TABLE public.assistant_storage_tickets OWNER TO assistant_evidence_owner" in text
    forbidden = (
        r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:public\.)?"
        r"(?:regimen_versions|dose_events|patient_medications|source_documents|health_observations|storage\.)\b"
    )
    assert not re.search(forbidden, text, re.I)
    assert not re.search(r"\bEXECUTE\s+(?:format|p_|v_)", text, re.I)


def test_roles_are_review_only_without_credentials_or_clinical_privileges():
    text = candidate("roles.review.sql")
    for attribute in ["NOINHERIT", "NOSUPERUSER", "NOCREATEDB", "NOCREATEROLE", "NOREPLICATION", "NOBYPASSRLS"]:
        assert attribute in text
    assert "PASSWORD" not in re.sub(r"--[^\n]*", "", text)
    assert "GRANT authenticated" not in text and "GRANT service_role" not in text
    assert "NOT APPLIED" in text


def test_metadata_down_preserves_earlier_workflow_and_clinical_tables():
    text = candidate("metadata.down.sql")
    drops = re.findall(r"DROP TABLE\s+(?:IF EXISTS\s+)?public\.(\w+)", text, re.I)
    assert set(drops) == {
        "assistant_storage_tickets",
        "assistant_verified_operations",
        "assistant_business_receipts",
        "assistant_runtime_runs",
        "assistant_runtime_events",
    }
    assert "assistant_workflow_tasks" not in drops and "source_documents" not in drops


@pytest.mark.skipif(
    os.environ.get("RUN_ASSISTANT_PERSISTENCE_TESTS") != "1" or os.environ.get("RUN_ASSISTANT_SQL_TESTS") != "1",
    reason="Actual restricted-role acceptance requires a separately approved isolated target",
)
def test_restricted_login_cannot_reach_clinical_privileges():
    import psycopg

    from tests.backend.persistent_workflow_live_support import admitted_live_profile, sql_connection_parameters

    profile, _ = admitted_live_profile("sql_read")
    try:
        connection = psycopg.connect(**sql_connection_parameters(profile, verifier=True, read_only=True))
    except psycopg.Error:
        pytest.fail("Approved isolated verifier connection unavailable", pytrace=False)
    with connection:
        assert connection.execute("SELECT session_user").fetchone()[0] == "assistant_evidence_login"
        assert not connection.execute(
            "SELECT has_table_privilege(current_user,'public.regimen_versions','SELECT')"
        ).fetchone()[0]
        assert not connection.execute(
            "SELECT has_function_privilege(current_user,'public.record_confirmed_self_report(jsonb)','EXECUTE')"
        ).fetchone()[0]
        assert not connection.execute("SELECT pg_has_role(session_user,'authenticated','MEMBER')").fetchone()[0]


def test_raw_cleanup_reference_contract_excludes_only_distinct_native_copy_receipts():
    text = candidate("originals.up.sql")
    gate = text[
        text.index(
            "OR EXISTS(SELECT 1 FROM public.assistant_workflow_operations WHERE owner=o AND record_type='action'"
        ) :
    ]
    gate = gate[: gate.index("THEN")]
    # Distinct derived-object receipts are not references to the raw original.
    # Unknown writers, formal sources and actual shared raw references remain guarded separately.
    assert "coalesce(data->>'capability_id','') NOT IN ('gallery.photo.add','library.pdf.add')" in gate
    assert "data->>'state' IN ('pending','outcome_unknown')" in gate
    assert "a->'source_ref'" in text and "assistant_original_deletions" in text
