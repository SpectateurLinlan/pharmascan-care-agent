"""Offline source contracts only; PostgreSQL execution is a separate target gate."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "supabase/review/assistant_workflows"


def test_release_marker_is_operator_published_and_never_inserted_by_installation():
    sql = (REVIEW / "runtime-readiness.up.sql").read_text(encoding="utf-8")
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "INSERT INTO" not in sql
    assert "REVOKE ALL ON TABLE assistant_evidence.runtime_releases" in sql
    assert "GRANT SELECT ON TABLE assistant_evidence.runtime_releases TO assistant_workflow_owner" in sql
    assert "evidence_digest" in sql and "revoked_at" in sql


def test_both_fixed_readers_use_one_catalog_bound_release_without_patient_rows():
    sql = (REVIEW / "runtime-readiness.up.sql").read_text(encoding="utf-8")
    assert "assistant_evidence.runtime_readiness()" in sql
    assert "public.assistant_runtime_readiness()" in sql
    assert "TO assistant_evidence_login, assistant_workflow_owner" in sql
    assert "public.assistant_runtime_readiness() TO authenticated" in sql
    assert "pg_catalog.pg_policy" in sql and "pg_catalog.pg_attribute" in sql
    assert "pg_catalog.pg_roles" in sql and "pg_catalog.pg_auth_members" in sql
    assert "pg_catalog.pg_get_functiondef" in sql
    assert "source_count = 1" in sql and "release.catalog_digest = observed_digest" in sql
    assert "SET search_path = pg_catalog, assistant_evidence" in sql
    assert "FROM public.medications" not in sql


def test_recovery_refuses_to_remove_any_release_history():
    sql = (REVIEW / "runtime-readiness.down.sql").read_text(encoding="utf-8")
    assert "EXISTS (SELECT 1 FROM assistant_evidence.runtime_releases)" in sql
    assert "RAISE EXCEPTION" in sql and "DELETE FROM" not in sql


def test_catalog_fingerprint_covers_enabled_integrity_guards_and_view_rules():
    sql = (REVIEW / "runtime-readiness.up.sql").read_text(encoding="utf-8")
    # Source contract only; real disable/re-enable trigger acceptance stays gated.
    for token in (
        "pg_catalog.pg_trigger",
        "pg_catalog.pg_get_triggerdef",
        "t.tgenabled",
        "pg_catalog.pg_rewrite",
        "pg_catalog.pg_get_ruledef",
        "c.convalidated",
        "i.indisvalid",
        "i.indisready",
        "i.indislive",
    ):
        assert token in sql
