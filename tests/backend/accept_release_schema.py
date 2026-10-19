"""Compare captured READ ONLY production metadata against isolated 026 and 029.

python -m tests.backend.accept_release_schema --run-isolated
Requires THREADS_TEST_DSN localhost and outputs/release/database-contracts.json.
Only the guarded local disposable environment is mutated; no production connection.
"""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from scripts.qa.database_contracts import read_inventory

from .test_conversation_threads_sql import db, initialize_platform


def difference(before, after):
    result = {}
    for key in ["tables", "columns", "functions", "constraints", "policies", "triggers", "grants"]:

        def rows(data, kind):
            values = data[kind]
            if kind == "tables":
                return {r["name"]: r for r in values if r["name"] != "core_schema_migrations"}
            if kind == "functions":
                return {r["name"] + "(" + r["arguments"] + ")": r for r in values if r["name"] != "rls_auto_enable"}
            return {
                json.dumps(r[:2] if kind not in {"columns", "grants"} else r): r
                for r in values
                if "core_schema_migrations" not in r
            }

        left, right = rows(before, key), rows(after, key)
        result[key] = {
            "removed": [left[k] for k in sorted(left.keys() - right.keys())],
            "added": [right[k] for k in sorted(right.keys() - left.keys())],
            "changed": [
                {"before": left[k], "after": right[k]}
                for k in sorted(left.keys() & right.keys())
                if left[k] != right[k]
            ],
        }
    return result


def run():
    import psycopg
    from psycopg import sql

    env = db.__wrapped__()
    target = next(env)
    try:
        folder = Path("outputs/release")
        production = json.loads((folder / "database-contracts.json").read_text(encoding="utf-8"))
        baseline_name = "mt_schema_baseline_" + uuid4().hex[:8]
        target.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(baseline_name)))
        with psycopg.connect(f"postgresql://postgres@127.0.0.1:55439/{baseline_name}", autocommit=True) as baseline:
            initialize_platform(baseline)
            for path in sorted(Path("supabase/migrations").glob("*.sql")):
                if path.name[:12] <= "202610170026":
                    baseline.execute(path.read_text(encoding="utf-8"))
            deployed_expected = read_inventory(baseline)
            known_tables = {r["name"] for r in deployed_expected["tables"]}
            for role, table, privilege in production["grants"]:
                if table not in known_tables:
                    continue
                assert role in {"anon", "authenticated", "service_role", "pharmascan_patient"}
                assert privilege in {
                    "SELECT",
                    "INSERT",
                    "UPDATE",
                    "DELETE",
                    "TRUNCATE",
                    "REFERENCES",
                    "TRIGGER",
                    "MAINTAIN",
                }
                baseline.execute(
                    sql.SQL("GRANT {} ON TABLE public.{} TO {}").format(
                        sql.SQL(privilege), sql.Identifier(table), sql.Identifier(role)
                    )
                )
            for path in sorted(Path("supabase/migrations").glob("*.sql")):
                if path.name[:12] > "202610170026":
                    baseline.execute(path.read_text(encoding="utf-8"))
            desired = read_inventory(baseline)
        report = {
            "mode": "Captured production READ ONLY vs real local026 and replay of027-029 over hosted grants",
            "platform_note": (
                "rls_auto_enable and migration ledger are retained platform/runner objects, not planned removals"
            ),
            "production_vs_026": difference(deployed_expected, production),
            "production_to_target029": difference(production, desired),
        }
        (folder / "schema-comparison.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    label: {k: {name: len(rows) for name, rows in value.items()} for k, value in report[label].items()}
                    for label in ["production_vs_026", "production_to_target029"]
                }
            )
        )
    finally:
        env.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-isolated", action="store_true", required=True)
    parser.parse_args()
    run()
