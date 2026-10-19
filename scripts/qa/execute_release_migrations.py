"""Explicitly authorized 027->028->029 production execution via existing scoped runner.

Requires the private-backup restore proof. No synthetic/real patient writes or
delete-RPC success tests. Stops on every mismatch; never retries a DDL failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings  # noqa: E402

from scripts.qa.database_contracts import inspect  # noqa: E402


def verify_contracts(version):
    import psycopg

    with psycopg.connect(
        Settings.from_env().require_database_url(), options="-c default_transaction_read_only=on"
    ) as c:
        c.execute("SET TRANSACTION READ ONLY")
        required = {
            "draft_rpc": c.execute(
                "SELECT to_regprocedure('public.delete_unconfirmed_medication(text,uuid,boolean)') IS NOT NULL"
            ).fetchone()[0],
            "receipt_rls": c.execute(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                "WHERE oid='public.draft_deletion_receipts'::regclass"
            ).fetchone()[0],
            "authenticated_rpc": c.execute(
                "SELECT has_function_privilege('authenticated',"
                "'public.delete_unconfirmed_medication(text,uuid,boolean)','EXECUTE')"
            ).fetchone()[0],
            "anon_rpc_denied": not c.execute(
                "SELECT has_function_privilege('anon',"
                "'public.delete_unconfirmed_medication(text,uuid,boolean)','EXECUTE')"
            ).fetchone()[0],
            "direct_plan_delete_denied": not c.execute(
                "SELECT has_table_privilege('authenticated','public.regimen_versions','DELETE')"
            ).fetchone()[0],
        }
        if version >= "202610180028":
            required["overlap_audit_allowed"] = c.execute(
                'SELECT core_trace_summary_is_safe(\'{"error_code":"REGIMEN_OVERLAP"}\')'
            ).fetchone()[0]
            required["free_text_audit_rejected"] = not c.execute(
                'SELECT core_trace_summary_is_safe(\'{"error_code":"arbitrary private text"}\')'
            ).fetchone()[0]
        if version >= "202610180029":
            required.update(
                {
                    "truncate_denied": not c.execute(
                        "SELECT has_table_privilege('authenticated','patient_medications','TRUNCATE')"
                    ).fetchone()[0],
                    "anon_read_denied": not c.execute(
                        "SELECT has_table_privilege('anon','patient_medications','SELECT')"
                    ).fetchone()[0],
                    "image_retirement_column_preserved": c.execute(
                        "SELECT has_column_privilege('authenticated','medication_images','data','UPDATE')"
                    ).fetchone()[0],
                    "legacy_thread_rpc_preserved": c.execute(
                        "SELECT has_function_privilege('authenticated','create_conversation(uuid,text)','EXECUTE')"
                    ).fetchone()[0],
                    "owned_medication_read_preserved": c.execute(
                        "SELECT has_table_privilege('authenticated','patient_medications','SELECT')"
                    ).fetchone()[0],
                    "owned_push_update_preserved": c.execute(
                        "SELECT has_table_privilege('authenticated','push_subscriptions','UPDATE')"
                    ).fetchone()[0],
                }
            )
        c.execute("SET LOCAL ROLE authenticated")
        c.execute("SELECT set_config('request.jwt.claim.sub','00000000-0000-0000-0000-000000000000',true)")
        required["unowned_medication_rows_hidden"] = (
            c.execute("SELECT count(*) FROM patient_medications").fetchone()[0] == 0
        )
        required["unowned_thread_rows_hidden"] = c.execute("SELECT count(*) FROM conversation_turns").fetchone()[0] == 0
        assert all(required.values()), "Contract check failed"
        return required


def run():
    proof = json.loads((ROOT / "outputs/release/backup-verification-20261019.json").read_text())
    assert proof.get("restore_verified") and proof.get("all_table_row_counts_and_digests_match")
    archive = Path(proof["private_folder"]) / "database.dump"
    assert ROOT not in archive.resolve().parents
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == proof["archive_sha256"]
    current = inspect()
    previous = json.loads((ROOT / "outputs/release/production-preflight-20261019.json").read_text())
    assert current["project_fingerprint"] == proof["project_fingerprint"] == previous["project_fingerprint"]
    assert all(previous["tested_migration_hashes_match"].values())
    before = {m["file"]: m for m in previous["migrations"]}
    authorized = {"202610180027", "202610180028", "202610180029"}
    scoped = [m for m in current["migrations"] if m["file"].split("_")[0] <= "202610180029"]
    assert all(m["sha256"] == before[m["file"]]["sha256"] for m in scoped)
    assert all(m["status"] == "APPLIED" for m in current["migrations"][:26])
    result = {
        "project_fingerprint": current["project_fingerprint"],
        "backup_verified": True,
        "steps": [],
        "patient_writes_or_test_deletes": False,
    }
    output = ROOT / "outputs/release/production-migrations-20261019.json"
    for migration in [m for m in scoped if m["file"].split("_")[0] in authorized]:
        version = migration["file"].split("_")[0]
        assert version in {"202610180027", "202610180028", "202610180029"}
        if migration["status"] == "APPLIED":
            # A resumed run verifies actual state rather than duplicating DDL.
            state = "already applied; verified without replay"
        else:
            assert migration["status"] == "PENDING"
            log = Path(proof["private_folder"]) / (version + "-runner.log")
            assert not log.exists(), "Prior execution log exists: inspect partial state before retrying"
            with log.open("wb") as handle:
                attempt = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/db.py"), "migrate", "--only", version],
                    cwd=ROOT,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    timeout=120,
                )
            if attempt.returncode:
                raise RuntimeError("Scoped runner failed; stop and inspect actual schema/ledger, do not replay")
            state = "executed"
        after = inspect()
        row = next(m for m in after["migrations"] if m["file"] == migration["file"])
        assert row["status"] == "APPLIED" and row["sha256"] == migration["sha256"]
        checks = verify_contracts(version)
        result["steps"].append({"version": version, "state": state, "ledger_hash_match": True, "checks": checks})
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({"version": version, "state": state, "contracts": "PASS"}), flush=True)
    final = inspect()
    (ROOT / "outputs/release/database-contracts-after-20261019.json").write_text(
        json.dumps(final, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorized-production-migrations", action="store_true", required=True)
    parser.parse_args()
    try:
        run()
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "STOPPED",
                    "error_type": type(error).__name__,
                    "reason": "Inspect private runner log and actual read-only ledger before any retry",
                }
            )
        )
        raise SystemExit(2) from None
