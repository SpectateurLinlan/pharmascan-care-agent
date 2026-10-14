"""Migration discovery, application and schema verification.

``supabase/migrations/*.sql`` is the **source of truth** (status/WORK_LOG.md
Gate 0/1). This module never generates DDL of its own for domain objects: it
applies the committed files verbatim and then verifies what the database
actually contains.

There is no ``supabase`` CLI, no ``psql`` and no Docker on this machine, so the
runner below is the developer-maintained executor. It is deliberately boring:
lexicographic order by filename, one transaction per file, abort on error.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"
ROLLBACK_DIR = REPO_ROOT / "supabase" / "rollback"

#: Runner-owned bookkeeping, NOT domain schema. It records which committed
#: migration file has been applied and its content hash, so a re-run is a
#: no-op and a mutated file is detected. It holds no patient data and is
#: created by the runner rather than by a migration file.
LEDGER_TABLE = "core_schema_migrations"

# Tables the core migration is expected to create, in dependency order.
CORE_TABLES: tuple[str, ...] = (
    "patient_profiles",
    "medication_products",
    "source_documents",
    "source_fields",
    "patient_medications",
    "regimen_versions",
    "dose_rules",
    "dose_occurrences",
    "agent_sessions",
    "confirmation_challenges",
    "dose_events",
    "agent_tool_calls",
    "audit_events",
)

# Patient-owned tables that must carry FORCE ROW LEVEL SECURITY.
RLS_REQUIRED_TABLES: tuple[str, ...] = (
    "patient_profiles",
    "source_documents",
    "source_fields",
    "patient_medications",
    "regimen_versions",
    "dose_rules",
    "dose_occurrences",
    "agent_sessions",
    "confirmation_challenges",
    "dose_events",
    "agent_tool_calls",
    "audit_events",
    "medication_products",
    "dose_reminders",
    "demo_ai_usage",
    "demo_ai_turns",
    "patient_feedback",
    "health_observations",
    "medication_evidence_tasks",
    "medication_source_links",
    "medication_images",
    "visual_reference_sets",
    "image_embeddings",
    "recognition_runs",
)


@dataclass(frozen=True)
class MigrationFile:
    version: str
    name: str
    path: Path
    sql: str
    sha256: str

    @property
    def label(self) -> str:
        return f"{self.version}_{self.name}"


def discover_migrations(directory: Path | None = None) -> list[MigrationFile]:
    """Return every ``*.sql`` migration in lexicographic (version) order."""
    root = directory or MIGRATIONS_DIR
    migrations: list[MigrationFile] = []
    for path in sorted(root.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        stem = path.stem
        version, _, name = stem.partition("_")
        migrations.append(
            MigrationFile(
                version=version,
                name=name or stem,
                path=path,
                sql=sql,
                sha256=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            )
        )
    return migrations


def apply_migration(connection: psycopg.Connection, migration: MigrationFile) -> None:
    """Execute one committed migration file.

    The caller must supply an autocommit connection: the migration files carry
    their own ``BEGIN``/``COMMIT`` so that a partially applied file can never be
    recorded as applied.
    """
    if not connection.autocommit:
        raise RuntimeError("migrations must run on an autocommit connection")
    with connection.cursor() as cursor:
        cursor.execute(migration.sql)  # type: ignore[arg-type]


def ensure_ledger(connection: psycopg.Connection) -> None:
    """Create the runner's migration ledger if it does not exist yet."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS public.{LEDGER_TABLE} (
                version text PRIMARY KEY,
                name text NOT NULL,
                sha256 text NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )


def applied_migrations(connection: psycopg.Connection) -> dict[str, str]:
    """Return ``{version: sha256}`` for every migration already recorded."""
    ensure_ledger(connection)
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT version, sha256 FROM public.{LEDGER_TABLE}")
        return {row["version"]: row["sha256"] for row in cursor.fetchall()}


def record_migration(connection: psycopg.Connection, migration: MigrationFile) -> None:
    """Record one applied migration (idempotent on version)."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO public.{LEDGER_TABLE} (version, name, sha256)
            VALUES (%s, %s, %s)
            ON CONFLICT (version) DO NOTHING
            """,
            (migration.version, migration.name, migration.sha256),
        )


def table_exists(connection: psycopg.Connection, table: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s) AS oid", (f"public.{table}",))
        row = cursor.fetchone()
    return bool(row and row["oid"])


def existing_core_tables(connection: psycopg.Connection) -> list[str]:
    return [table for table in CORE_TABLES if table_exists(connection, table)]


def _rows(connection: psycopg.Connection, sql: str, params: tuple = ()) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


def inspect_rls(connection: psycopg.Connection) -> dict[str, dict[str, bool]]:
    """Report RLS enablement and policy presence per table (read-only)."""
    rows = _rows(
        connection,
        """
        SELECT c.relname AS table_name,
               c.relrowsecurity AS rls_enabled,
               c.relforcerowsecurity AS rls_forced,
               (SELECT count(*) FROM pg_policies p
                 WHERE p.schemaname = 'public' AND p.tablename = c.relname) AS policy_count
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname = ANY(%s)
         ORDER BY c.relname
        """,
        (list(RLS_REQUIRED_TABLES),),
    )
    return {
        row["table_name"]: {
            "rls_enabled": row["rls_enabled"],
            "rls_forced": row["rls_forced"],
            "has_policy": row["policy_count"] > 0,
        }
        for row in rows
    }


def inspect_tables(connection: psycopg.Connection) -> dict[str, dict[str, object]]:
    """Per-table primary key / foreign key / index / check counts (read-only)."""
    names = list(CORE_TABLES)
    constraints = _rows(
        connection,
        """
        SELECT c.relname AS table_name, con.contype AS kind, count(*) AS n
          FROM pg_constraint con
          JOIN pg_class c ON c.oid = con.conrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relname = ANY(%s)
         GROUP BY 1, 2
        """,
        (names,),
    )
    indexes = _rows(
        connection,
        """
        SELECT t.relname AS table_name, count(*) AS n
          FROM pg_index i
          JOIN pg_class t ON t.oid = i.indrelid
          JOIN pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname = 'public' AND t.relname = ANY(%s)
         GROUP BY 1
        """,
        (names,),
    )
    index_map = {row["table_name"]: row["n"] for row in indexes}
    result: dict[str, dict[str, object]] = {
        table: {
            "exists": table_exists(connection, table),
            "primary_key": 0,
            "foreign_keys": 0,
            "unique": 0,
            "check": 0,
            "indexes": index_map.get(table, 0),
        }
        for table in names
    }
    kind_map = {"p": "primary_key", "f": "foreign_keys", "u": "unique", "c": "check"}
    for row in constraints:
        target = result.get(row["table_name"])
        key = kind_map.get(row["kind"])
        if target is not None and key is not None:
            target[key] = row["n"]
    return result


def inspect_grants(connection: psycopg.Connection) -> dict[str, list[str]]:
    """Table privileges per role, to prove authenticated is read-only."""
    rows = _rows(
        connection,
        """
        SELECT grantee, privilege_type, count(*) AS n
          FROM information_schema.role_table_grants
         WHERE table_schema = 'public'
           AND table_name = ANY(%s)
           AND grantee IN ('authenticated', 'anon', 'service_role', 'PUBLIC')
         GROUP BY 1, 2 ORDER BY 1, 2
        """,
        (list(CORE_TABLES),),
    )
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(row["grantee"], []).append(f"{row['privilege_type']}:{row['n']}")
    return result


def inspect_functions(connection: psycopg.Connection) -> list[str]:
    rows = _rows(
        connection,
        """
        SELECT p.proname FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public' AND p.proname ~ '^core_'
         ORDER BY p.proname
        """,
    )
    return [row["proname"] for row in rows]


def inspect_triggers(connection: psycopg.Connection) -> dict[str, list[str]]:
    rows = _rows(
        connection,
        """
        SELECT c.relname AS table_name, t.tgname AS trigger_name
          FROM pg_trigger t
          JOIN pg_class c ON c.oid = t.tgrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND NOT t.tgisinternal AND c.relname = ANY(%s)
         ORDER BY 1, 2
        """,
        (list(CORE_TABLES),),
    )
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(row["table_name"], []).append(row["trigger_name"])
    return result


def inspect_agent_allowlists(connection: psycopg.Connection) -> dict[str, object]:
    """Read back the agent enum CHECKs and the redaction function definition.

    Used to prove that migration 202610130002 actually closed the three
    allowlist gaps rather than assuming it did.
    """
    rows = _rows(
        connection,
        """
        SELECT con.conname AS name, pg_get_constraintdef(con.oid) AS definition
          FROM pg_constraint con
          JOIN pg_class c ON c.oid = con.conrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND con.conname IN (
               'agent_tool_calls_tool_name_check', 'agent_sessions_intent_check')
        """,
    )
    definitions = {row["name"]: row["definition"] for row in rows}
    functions = _rows(
        connection,
        """
        SELECT pg_get_functiondef(p.oid) AS definition
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public' AND p.proname = 'core_trace_summary_is_safe'
        """,
    )
    source = functions[0]["definition"] if functions else ""
    checks = {
        "tool_name_allows_get_dose_status": "'get_dose_status'"
        in definitions.get("agent_tool_calls_tool_name_check", ""),
        "intent_allows_dose_status_query": "'dose_status_query'" in definitions.get("agent_sessions_intent_check", ""),
        "trace_allows_already_recorded": "'already_recorded'" in source,
        "trace_allows_missing_count": "'missing_count'" in source,
        "trace_allows_no_report": "'no_report'" in source,
        "trace_still_bounded_1024": "1024" in source,
        # pg_get_functiondef renders the jsonb literal as '"not_checked"'::jsonb,
        # so match the bare token rather than a quoted form.
        "trace_still_not_checked_only": "not_checked" in source,
    }
    return {
        "checks": checks,
        "all_present": all(checks.values()),
        "definitions": definitions,
    }


def inspect_storage(connection: psycopg.Connection) -> dict[str, object]:
    """Report bucket visibility and storage.objects policy coverage (read-only).

    Live storage verification is IN_PROGRESS: the policies exist and are
    checked here, but no object is uploaded, because the P0 slice has no photo
    path and real health data must never be uploaded.
    """
    buckets = _rows(
        connection,
        "SELECT id, public FROM storage.buckets WHERE id = ANY(%s) ORDER BY id",
        (["medication-sources", "visual-references"],),
    )
    policies = _rows(
        connection,
        """
        SELECT policyname, cmd FROM pg_policies
         WHERE schemaname = 'storage' AND tablename = 'objects'
           AND policyname LIKE 'pharmascan_objects_%%'
         ORDER BY policyname
        """,
    )
    expected_buckets = {"medication-sources", "visual-references"}
    present_buckets = {row["id"] for row in buckets}
    return {
        "buckets": [{"id": row["id"], "public": row["public"]} for row in buckets],
        "buckets_present": sorted(present_buckets),
        "missing_buckets": sorted(expected_buckets - present_buckets),
        "all_private": all(row["public"] is False for row in buckets),
        "policies": [{"name": row["policyname"], "command": row["cmd"]} for row in policies],
        "policy_count": len(policies),
        "ownership_model": "<patient_id>/<opaque-filename> — first path segment must equal auth.uid()",
        "live_verification": "SCHEMA_ONLY",
        "live_verification_reason": "This read-only command checks bucket policies only. "
        "Synthetic authenticated upload/read/delete isolation is tested separately in test_supabase_live.py.",
    }


def server_identity(connection: psycopg.Connection) -> dict[str, str]:
    rows = _rows(
        connection,
        """
        SELECT current_database() AS database,
               current_user AS role,
               version() AS version,
               (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) AS is_superuser
        """,
    )
    row = rows[0]
    return {
        "database": row["database"],
        "role": row["role"],
        "version": row["version"].split(" on ")[0],
        "is_superuser": str(row["is_superuser"]),
    }
