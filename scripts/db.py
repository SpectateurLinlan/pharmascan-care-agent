"""Developer database CLI for the Supabase/Postgres development project.

Usage (from the repository root, with the managed interpreter):

    python scripts/db.py status     # settings presence + masked target + schema state
    python scripts/db.py migrate    # apply committed supabase/migrations/*.sql in order
    python scripts/db.py verify     # full read-only schema/RLS report -> outputs/

Rules honoured here:
- ``supabase/migrations/*.sql`` is the only source of DDL; this script never
  creates or alters a domain table of its own;
- no credential value is ever printed, logged or written to a report;
- nothing is dropped, truncated or deleted.

Configuration comes from the process environment, or from a dotenv file named
by ``PHARMASCAN_ENV_FILE``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import ConfigError, Settings  # noqa: E402
from app.infrastructure.postgres_db import PostgresDatabase  # noqa: E402
from app.infrastructure.postgres_migrations import (  # noqa: E402
    CORE_TABLES,
    RLS_REQUIRED_TABLES,
    applied_migrations,
    apply_migration,
    discover_migrations,
    ensure_ledger,
    existing_core_tables,
    inspect_agent_allowlists,
    inspect_functions,
    inspect_grants,
    inspect_rls,
    inspect_storage,
    inspect_tables,
    inspect_triggers,
    record_migration,
    server_identity,
)

REPORT_PATH = REPO_ROOT / "outputs" / "db_schema_report.json"


def _settings() -> Settings:
    settings = Settings.from_env()
    print("settings:", json.dumps(settings.describe(), sort_keys=True))
    return settings


def _database(settings: Settings) -> PostgresDatabase:
    try:
        dsn = settings.require_database_url()
    except ConfigError as exc:
        print(f"BLOCKED: {exc}")
        raise SystemExit(2) from exc
    database = PostgresDatabase(dsn=dsn)
    print("target:", database.target.description)
    return database


def cmd_status(args: argparse.Namespace) -> int:
    settings = _settings()
    database = _database(settings)
    with database.connect() as connection:
        print("server:", json.dumps(server_identity(connection), sort_keys=True))
        present = existing_core_tables(connection)
        print(f"core tables present: {len(present)}/{len(CORE_TABLES)}")
        for table in CORE_TABLES:
            print(f"  {'yes' if table in present else 'NO '} {table}")
        if present:
            print("rls:", json.dumps(inspect_rls(connection), sort_keys=True))
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    """Apply every committed migration that has not been applied yet.

    Order is lexicographic by filename. Each file carries its own
    ``BEGIN``/``COMMIT`` on an autocommit connection, so a partially applied
    file can never be recorded as applied. A migration whose recorded hash no
    longer matches the file on disk is reported and skipped rather than
    silently re-run.
    """
    settings = _settings()
    database = _database(settings)
    migrations = discover_migrations()
    if not migrations:
        print("no migrations found")
        return 1

    results: list[dict[str, object]] = []
    with database.connect(autocommit=True) as connection:
        ensure_ledger(connection)
        recorded = applied_migrations(connection)

        # Backfill: the core migration was applied before the ledger existed.
        # Detect that state from the schema itself rather than assuming it.
        if not recorded and len(existing_core_tables(connection)) == len(CORE_TABLES):
            core = migrations[0]
            record_migration(connection, core)
            recorded = applied_migrations(connection)
            print(f"ledger seeded: {core.label} recorded as already applied")

        for migration in migrations:
            known = recorded.get(migration.version)
            if known == migration.sha256:
                print(f"skip {migration.label} (already applied)")
                results.append(
                    {
                        "migration": migration.label,
                        "sha256": migration.sha256,
                        "outcome": "already_applied",
                    }
                )
                continue
            if known is not None:
                print(
                    f"WARNING: {migration.label} was applied with a different content hash; "
                    "refusing to re-run. Investigate before proceeding."
                )
                results.append(
                    {
                        "migration": migration.label,
                        "sha256": migration.sha256,
                        "recorded_sha256": known,
                        "outcome": "hash_mismatch",
                    }
                )
                continue

            print(f"applying {migration.label} (sha256 {migration.sha256[:12]}...)")
            try:
                apply_migration(connection, migration)
            except Exception as exc:  # noqa: BLE001 - reported verbatim, no secrets
                message = str(exc).strip().splitlines()[0]
                print(f"FAILED {migration.label}: {type(exc).__name__}: {message}")
                results.append(
                    {
                        "migration": migration.label,
                        "sha256": migration.sha256,
                        "outcome": "failed",
                        "error_type": type(exc).__name__,
                        "error": message,
                    }
                )
                _write_report(database, results, applied=False)
                return 4
            record_migration(connection, migration)
            results.append(
                {
                    "migration": migration.label,
                    "sha256": migration.sha256,
                    "outcome": "applied",
                }
            )
            print(f"applied {migration.label}")

        report = _write_report(database, results, applied=True)
    print(
        json.dumps(
            {
                "outcome": report["outcome"],
                "tables_present": report["tables_present"],
                "agent_allowlists": report["agent_allowlists"],
            },
            indent=2,
        )
    )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    settings = _settings()
    database = _database(settings)
    with database.connect() as connection:
        report = _write_report(database, [], applied=None, connection=connection)
    print(json.dumps(report["rls"], indent=2))
    print(f"report written: {REPORT_PATH.relative_to(REPO_ROOT)}")
    return 0 if report["outcome"] == "verified" else 5


def _write_report(
    database: PostgresDatabase,
    migrations: list[dict[str, object]],
    *,
    applied: bool | None,
    connection=None,
) -> dict:
    def build(conn) -> dict:
        tables = inspect_tables(conn)
        rls = inspect_rls(conn)
        missing = [t for t in CORE_TABLES if not tables[t]["exists"]]
        rls_gaps = [
            t
            for t in RLS_REQUIRED_TABLES
            if not (rls.get(t, {}).get("rls_enabled") and rls.get(t, {}).get("rls_forced"))
        ]
        policy_gaps = [t for t in RLS_REQUIRED_TABLES if not rls.get(t, {}).get("has_policy")]
        return {
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "evidence_kind": "VERIFIED_REAL_SUPABASE_READONLY_SCHEMA",
            "target": database.target.description,
            "server": server_identity(conn),
            "migrations": migrations,
            "tables_present": len(CORE_TABLES) - len(missing),
            "tables_expected": len(CORE_TABLES),
            "missing_tables": missing,
            "tables": tables,
            "rls": rls,
            "rls_gaps": rls_gaps,
            "policy_gaps": policy_gaps,
            "grants": inspect_grants(conn),
            "functions": inspect_functions(conn),
            "triggers": inspect_triggers(conn),
            "agent_allowlists": inspect_agent_allowlists(conn),
            "storage": inspect_storage(conn),
            "outcome": "verified" if not missing and not rls_gaps and not policy_gaps else "incomplete",
        }

    if connection is not None:
        report = build(connection)
    else:
        with database.connect() as conn:
            report = build(conn)
    if applied is not None:
        report["migrate_run"] = applied
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("migrate").set_defaults(func=cmd_migrate)
    sub.add_parser("verify").set_defaults(func=cmd_verify)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
