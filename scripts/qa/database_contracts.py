"""Read-only release schema inventory. Never applies migrations or reads patient rows.

Run: python scripts/qa/database_contracts.py --production-read-only
Credentials: existing Settings database/Supabase configuration. Output is scrubbed metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.infrastructure.postgres_migrations import discover_migrations  # noqa: E402


def inspect() -> dict:
    import psycopg

    settings = Settings.from_env()
    dsn = settings.require_database_url()
    target = urlparse(dsn)
    project = urlparse(settings.require_supabase_url()).hostname.split(".")[0]
    # Session-pool usernames carry the project ref; direct hosts carry it in the hostname.
    if project not in (target.hostname or "") and project not in (target.username or ""):
        raise RuntimeError("Database and configured Supabase project identities do not match")
    result = {
        "mode": "production metadata READ ONLY",
        "project_fingerprint": hashlib.sha256(project.encode()).hexdigest()[:12],
    }
    with psycopg.connect(dsn, connect_timeout=12, options="-c default_transaction_read_only=on") as c:
        c.execute("SET TRANSACTION READ ONLY")
        assert c.execute("show transaction_read_only").fetchone()[0] == "on"
        result.update(read_inventory(c))
    return result


def read_inventory(c) -> dict:
    """Read public metadata from an injected connection; no patient rows or DDL."""
    result = {}
    # Keep this inventory query visibly read-only, independent of migration-runner setup.
    ledger = c.execute("select to_regclass('public.core_schema_migrations')").fetchone()[0]
    applied = dict(c.execute("select version,sha256 from public.core_schema_migrations")) if ledger else {}
    result["migrations"] = [
        {
            "file": m.path.name,
            "sha256": m.sha256,
            "status": "APPLIED"
            if applied.get(m.version) == m.sha256
            else "HASH_MISMATCH"
            if m.version in applied
            else "PENDING",
        }
        for m in discover_migrations()
    ]
    result["tables"] = [
        {"name": name, "rls": rls, "force_rls": force}
        for name, rls, force in c.execute(
            "select relname,relrowsecurity,relforcerowsecurity from "
            "pg_class p join pg_namespace n on n.oid=p.relnamespace "
            "where n.nspname='public' and relkind='r' order by relname"
        )
    ]
    result["columns"] = [
        list(r)
        for r in c.execute(
            "select table_name,column_name,data_type from "
            "information_schema.columns where table_schema='public' order by table_name,ordinal_position"
        )
    ]
    result["functions"] = [
        {
            "name": name,
            "arguments": args,
            "definition_sha256": hashlib.sha256(definition.encode()).hexdigest(),
            "security_definer": sec,
        }
        for name, args, definition, sec in c.execute(
            "select proname,pg_get_function_identity_arguments(p.oid),pg_get_functiondef(p.oid),prosecdef "
            "from pg_proc p join pg_namespace n on "
            "n.oid=p.pronamespace where n.nspname='public' and prokind='f' order by proname"
        )
    ]
    result["policies"] = [
        list(r)
        for r in c.execute(
            "select tablename,policyname,roles::text,cmd,qual,with_check from "
            "pg_policies where schemaname='public' order by tablename,policyname"
        )
    ]
    result["constraints"] = [
        list(r)
        for r in c.execute(
            "select r.relname,c.conname,pg_get_constraintdef(c.oid) "
            "from pg_constraint c join pg_class r on r.oid=c.conrelid "
            "join pg_namespace n on n.oid=r.relnamespace where n.nspname='public' order by r.relname,c.conname"
        )
    ]
    result["triggers"] = [
        list(row)
        for row in c.execute(
            "select r.relname,t.tgname,pg_get_triggerdef(t.oid) from pg_trigger t "
            "join pg_class r on r.oid=t.tgrelid join pg_namespace n on n.oid=r.relnamespace "
            "where n.nspname='public' and not t.tgisinternal order by r.relname,t.tgname"
        )
    ]
    result["grants"] = [
        list(row)
        for row in c.execute(
            "select r.rolname,p.relname,a.privilege_type from pg_class p "
            "join pg_namespace n on n.oid=p.relnamespace "
            "cross join lateral aclexplode(coalesce(p.relacl,acldefault('r',p.relowner))) a "
            "join pg_roles r on r.oid=a.grantee where n.nspname='public' and p.relkind in ('r','p') "
            "and r.rolname in ('anon','authenticated','pharmascan_patient','service_role') "
            "order by p.relname,r.rolname,a.privilege_type"
        )
    ]
    result["default_acl"] = [
        list(row)
        for row in c.execute(
            "select r.rolname,n.nspname,d.defaclobjtype,d.defaclacl::text from pg_default_acl d "
            "join pg_roles r on r.oid=d.defaclrole left join pg_namespace n on n.oid=d.defaclnamespace "
            "where n.nspname='public' or d.defaclnamespace=0 order by r.rolname,n.nspname,d.defaclobjtype"
        )
    ]
    result["column_grants"] = [
        list(row)
        for row in c.execute(
            "select grantee,table_name,column_name,privilege_type from information_schema.role_column_grants "
            "where table_schema='public' and grantee='authenticated' order by table_name,column_name,privilege_type"
        )
    ]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-read-only", action="store_true", required=True)
    parser.parse_args()
    try:
        result = inspect()
    except Exception as error:
        result = {"status": "BLOCKED", "error_type": type(error).__name__}
    output = ROOT / "outputs/release/database-contracts.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "mode": result.get("mode"),
                "error_type": result.get("error_type"),
                "migration_statuses": {
                    status: sum(m["status"] == status for m in result.get("migrations", []))
                    for status in ["APPLIED", "PENDING", "HASH_MISMATCH"]
                },
            }
        )
    )
    if result.get("status") == "BLOCKED":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
