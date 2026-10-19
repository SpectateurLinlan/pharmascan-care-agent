"""Read-only production catalog/public release probes; never reads patient rows."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402
import psycopg  # noqa: E402
from app.config import Settings  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402


def inspect(*, catalog_only: bool = False) -> dict:
    settings = Settings.from_env()
    report = {"observed_at": datetime.now(UTC).isoformat()}
    names = [
        "medication_library_files",
        "medication_library_file_audit",
        "medication_image_audit",
        "effective_dose_events",
        "dose_report_entries",
        "patient_profiles",
        "patient_medications",
        "regimen_versions",
        "dose_rules",
        "dose_occurrences",
        "dose_events",
        "dose_reminders",
        "medication_images",
        "medication_source_links",
        "source_documents",
        "source_fields",
        "image_embeddings",
        "visual_reference_sets",
        "recognition_runs",
        "inventory_transactions",
        "medication_evidence_tasks",
    ]
    try:
        with psycopg.connect(
            settings.require_database_url(),
            connect_timeout=15,
            row_factory=dict_row,
            options="-c default_transaction_read_only=on -c statement_timeout=15000",
        ) as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            report["read_only"] = connection.execute("show transaction_read_only").fetchone()
            assert report["read_only"]["transaction_read_only"] == "on"
            report["ledger"] = connection.execute(
                "select version,name,sha256,applied_at::text from public.core_schema_migrations order by version"
            ).fetchall()
            report["cli_ledger"] = connection.execute(
                "select to_regclass('supabase_migrations.schema_migrations')::text as relation"
            ).fetchone()
            if report["cli_ledger"]["relation"]:
                report["cli_versions"] = connection.execute(
                    "select version from supabase_migrations.schema_migrations order by version"
                ).fetchall()
            report["objects"] = connection.execute(
                "select n.nspname schema,c.relname name,c.relkind kind,c.relrowsecurity rls,"
                "c.relforcerowsecurity force_rls,"
                "has_table_privilege('authenticated',c.oid,'select') authenticated_select "
                "from pg_class c join pg_namespace n on n.oid=c.relnamespace "
                "where c.relname=any(%s) and n.nspname not in ('pg_catalog','information_schema') order by 1,2",
                (names,),
            ).fetchall()
            report["rest_schema_settings"] = connection.execute(
                "select setting from pg_db_role_setting, unnest(setconfig) as setting "
                "where setting like 'pgrst.db_schemas=%%'"
            ).fetchall()
            report["buckets"] = connection.execute(
                "select id,public,file_size_limit,allowed_mime_types from storage.buckets "
                "where id in ('medication-sources','personal-references')"
            ).fetchall()
            report["storage_policies"] = connection.execute(
                "select policyname,cmd,roles,qual,with_check from pg_policies "
                "where schemaname='storage' and tablename='objects' order by policyname"
            ).fetchall()
    except (psycopg.Error, OSError) as exc:
        report["database_error"] = type(exc).__name__
    if catalog_only:
        return report
    with httpx.Client(timeout=40, follow_redirects=True) as http:
        for origin in ["https://medithread-patient-api.onrender.com", "https://medithread.vercel.app"]:
            for path in ["/api/health", "/openapi.json"]:
                try:
                    response = http.get(origin + path)
                    item = {"status": response.status_code, "date": response.headers.get("date")}
                    if response.status_code == 200 and "json" in response.headers.get("content-type", ""):
                        data = response.json()
                        if path.endswith("health"):
                            item["health"] = data
                        else:
                            item["routes"] = [
                                p
                                for p in data.get("paths", {})
                                if any(
                                    k in p
                                    for k in [
                                        "gallery",
                                        "library",
                                        "regimen",
                                        "medication-history",
                                        "late-report",
                                        "alerts",
                                    ]
                                )
                            ]
                    report[origin + path] = item
                except httpx.HTTPError as exc:
                    report[origin + path] = {"error": type(exc).__name__}
        for endpoint in ["deployments?per_page=5", "commits/main/status"]:
            try:
                response = http.get(
                    "https://api.github.com/repos/SpectateurLinlan/pharmascan-care-agent/" + endpoint,
                    headers={"Accept": "application/vnd.github+json"},
                )
                data = response.json()
                report["github/" + endpoint] = {
                    "status": response.status_code,
                    "data": [{k: d.get(k) for k in ["sha", "created_at", "environment", "statuses_url"]} for d in data]
                    if isinstance(data, list)
                    else {k: data.get(k) for k in ["sha", "state", "statuses"]},
                }
            except httpx.HTTPError as exc:
                report["github/" + endpoint] = {"error": type(exc).__name__}
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-only", action="store_true")
    args = parser.parse_args()
    result = inspect(catalog_only=args.catalog_only)
    output = ROOT / f"outputs/incident031/read-only-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, default=str))
