"""Offline inventory by default. Explicit isolated read mode never applies SQL or calls clinical functions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from tests.backend.persistent_workflow_live_support import (  # noqa: E402
    PersistentProfileRefusal,
    PersistentWorkflowTestProfile,
    candidate_hashes,
    sql_connection_parameters,
    validate_persistent_test_profile,
)

TECHNICAL_COMMANDS = tuple(
    "assistant_evidence." + name + "(jsonb)"
    for name in (
        "record_storage_observation",
        "record_run_observation",
        "record_media_storage_observation",
        "record_media_delete_observation",
        "record_native_media_observation",
    )
) + ("assistant_evidence.runtime_readiness()",)
PATIENT_COMMANDS = (
    "public.assistant_runtime_readiness()",
    "public.assistant_workflow_mutate(jsonb)",
    "public.assistant_message_command(jsonb)",
    "public.assistant_conversation_transition(jsonb)",
    "public.assistant_notification_transition(jsonb)",
    "public.assistant_run_control(jsonb)",
    "public.assistant_original_command(jsonb)",
    "public.assistant_original_object_access(uuid,uuid,text)",
    "public.assistant_native_media_command(jsonb)",
    *tuple(
        f"public.assistant_{family}_{phase}(jsonb)"
        for family in ("medication", "record", "care", "media", "settings", "reminder")
        for phase in ("write", "read")
    ),
)
_TECHNICAL_TABLES = (
    "assistant_storage_tickets",
    "assistant_verified_operations",
    "assistant_runtime_runs",
    "assistant_runtime_events",
    "assistant_media_copy_tickets",
    "assistant_media_copy_verifications",
    "assistant_media_delete_tickets",
    "assistant_media_delete_verifications",
    "assistant_native_media_deletions",
    "assistant_native_file_intents",
    "assistant_native_file_observations",
)
_COMMAND_QUERY = """SELECT name,to_regprocedure(name) IS NOT NULL,
 has_function_privilege(%s,to_regprocedure(name),'EXECUTE'),
 has_function_privilege(%s,to_regprocedure(name),'EXECUTE') FROM unnest(%s::text[]) name ORDER BY name"""
READ_QUERIES = {
    "identity": """SELECT session_user,current_user,r.rolsuper,r.rolcreatedb,r.rolcreaterole,r.rolreplication,
 r.rolbypassrls,r.rolinherit,EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.member=r.oid)
 FROM pg_catalog.pg_roles r WHERE r.rolname=session_user""",
    "database": "SELECT current_database()",
    "commands": _COMMAND_QUERY,
    "patient_commands": _COMMAND_QUERY.replace("ORDER BY name", "ORDER BY name DESC"),
    "login_tables": """SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname IN ('public','storage','auth') AND c.relkind IN ('r','p','v','m','f')
 AND has_table_privilege(session_user,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')""",
    "owner_tables": """SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname IN ('public','storage','auth') AND c.relkind IN ('r','p','v','m','f')
 AND NOT(c.relname=ANY(%s::text[]))
 AND has_table_privilege('assistant_evidence_owner',c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')""",
    "privileged_functions": """SELECT count(*) FROM pg_catalog.pg_proc p
 JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('public','auth','storage') AND p.prosecdef
 AND (has_function_privilege(session_user,p.oid,'EXECUTE')
 OR has_function_privilege('assistant_evidence_owner',p.oid,'EXECUTE'))""",
    "extra_technical": """SELECT count(*) FROM pg_catalog.pg_proc p
 JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='assistant_evidence'
 AND NOT(p.oid=ANY(ARRAY(SELECT to_regprocedure(x)::oid FROM unnest(%s::text[]) x)))
 AND has_function_privilege(session_user,p.oid,'EXECUTE')""",
    "owner_privileges": """SELECT CASE WHEN count(*)<>1 THEN 1 ELSE count(*) FILTER(WHERE rolcanlogin OR rolsuper
 OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls OR rolinherit
 OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.member=r.oid)) END
 FROM pg_catalog.pg_roles r WHERE rolname='assistant_evidence_owner'""",
    "definitions": """SELECT p.oid::regprocedure::text,
 encode(sha256(convert_to(pg_get_functiondef(p.oid),'UTF8')),'hex')
 FROM pg_catalog.pg_proc p WHERE p.oid=ANY(ARRAY(SELECT to_regprocedure(x)::oid FROM unnest(%s::text[]) x))
 ORDER BY 1""",
}


def inventory():
    return {
        "schema_version": 1,
        "status": "NOT_RUN",
        "network_calls": 0,
        "execution_ready": False,
        "candidate_hashes": candidate_hashes(),
        "roles": [
            "assistant_evidence_login",
            "assistant_evidence_owner",
            "assistant_workflow_owner",
            "assistant_message_owner",
        ],
        "technical_commands": TECHNICAL_COMMANDS,
        "patient_commands": PATIENT_COMMANDS,
        "required_observations": [
            "role flags and memberships",
            "PUBLIC and definer closure",
            "patient isolation",
            "applied function/ledger hashes",
            "ordinary native compatibility",
            "writer/reference/absence proof races",
            "nonempty rollback refusal",
        ],
    }


def inspect_read_only(profile, target, *, connect=None):
    """Bounded catalog reads on the restricted identity; no supplied SQL or patient row data."""
    admitted = validate_persistent_test_profile(profile, purpose="sql_read", require_hashes=True)
    if admitted != target:
        raise PersistentProfileRefusal()
    if profile.target_mode == "local_supabase":
        from tests.backend.local_supabase_live_support import verify_local_live_target

        verify_local_live_target(profile, target)
    if connect is None:
        import psycopg

        connect = psycopg.connect
    kwargs = sql_connection_parameters(profile, verifier=True, read_only=True)
    from urllib.parse import urlparse

    with connect(**kwargs) as connection:
        identity = connection.execute(READ_QUERIES["identity"]).fetchone()
        if identity is None or tuple(identity[:2]) != ("assistant_evidence_login", "assistant_evidence_login"):
            raise PersistentProfileRefusal()
        if any(value is not False for value in identity[2:]):
            raise PersistentProfileRefusal()
        database = connection.execute(READ_QUERIES["database"]).fetchone()
        if database is None or database[0] != urlparse(profile.database_url).path[1:]:
            raise PersistentProfileRefusal()
        technical = connection.execute(
            READ_QUERIES["commands"], ("assistant_evidence_login", "authenticated", list(TECHNICAL_COMMANDS))
        ).fetchall()
        patient = connection.execute(
            READ_QUERIES["patient_commands"], ("authenticated", "assistant_evidence_login", list(PATIENT_COMMANDS))
        ).fetchall()
        counts = {}
        params = {"owner_tables": (list(_TECHNICAL_TABLES),), "extra_technical": (list(TECHNICAL_COMMANDS),)}
        for key in ("login_tables", "owner_tables", "privileged_functions", "extra_technical", "owner_privileges"):
            row = connection.execute(READ_QUERIES[key], params.get(key)).fetchone()
            counts[key] = row[0] if row is not None and type(row[0]) is int else -1
        definitions = connection.execute(
            READ_QUERIES["definitions"], (list(TECHNICAL_COMMANDS + PATIENT_COMMANDS),)
        ).fetchall()
    good = (
        len(technical) == len(TECHNICAL_COMMANDS)
        and len(patient) == len(PATIENT_COMMANDS)
        and all(tuple(row[1:]) == (True, True, False) for row in [*technical, *patient])
        and all(count == 0 for count in counts.values())
    )
    return {
        "status": "READ_ONLY_OBSERVED",
        "acl_observation": "PASS" if good else "FAIL",
        "execution_ready": False,
        "target_fingerprint": target.database_fingerprint,
        "catalog_query_count": len(READ_QUERIES),
        "unexpected_privilege_counts": counts,
        "applied_function_hashes": dict(definitions),
        "business_storage_provider_acceptance": "NOT_RUN",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--allow-isolated-read", action="store_true")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    result, code = inventory(), 0
    if args.read_only:
        try:
            if not args.allow_isolated_read or args.profile is None or args.profile.suffix != ".json":
                raise PersistentProfileRefusal()
            values = json.loads(args.profile.read_text(encoding="utf-8"))
            profile = PersistentWorkflowTestProfile.from_values(values)
            target = validate_persistent_test_profile(profile, purpose="sql_read", require_hashes=True)
            result.update(inspection_attempted=True, network_calls=None)
            result = inspect_read_only(profile, target)
            code = 0 if result["acl_observation"] == "PASS" else 2
        except Exception:
            attempted = result.get("inspection_attempted", False)
            result.update(
                reason="observation_unavailable" if attempted else "target_not_authorized",
                status="READ_ONLY_UNAVAILABLE" if attempted else "NOT_RUN",
                execution_ready=False,
            )
            code = 2  # No raw exception, DSN, token or connection parameters in diagnostics.
    if args.output:
        from scripts.qa.eval_assistant import private_output

        output = private_output(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
