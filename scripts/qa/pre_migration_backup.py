"""Explicit owner-authorized production READ ONLY backup, private isolated restore.

python scripts/qa/pre_migration_backup.py --authorized-production-backup --backup-root D:/MediThread-private-backups
All archives, Auth/patient rows, SQL, credentials and restore logs stay OUTSIDE Git.
No production writes. The archive includes DB metadata, not Storage object bytes,
platform secrets, network/Cron execution state, PITR or provider configuration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings  # noqa: E402


def fingerprints(connection):
    from psycopg import sql

    values = {}
    tables = connection.execute(
        "SELECT schemaname,tablename FROM pg_tables WHERE schemaname IN ('public','auth','storage') "
        "ORDER BY schemaname,tablename"
    ).fetchall()
    for schema, table in tables:
        count, digest = connection.execute(
            sql.SQL(
                "SELECT count(*),md5(coalesce(string_agg(md5(to_jsonb(t)::text),'' "
                "ORDER BY md5(to_jsonb(t)::text)),'')) FROM {}.{} t"
            ).format(sql.Identifier(schema), sql.Identifier(table))
        ).fetchone()
        values[f"{schema}.{table}"] = {"rows": count, "digest": digest}
    return values


def run(backup_root: Path, existing: Path | None = None):
    import psycopg
    from psycopg import sql

    if ROOT == backup_root.resolve() or ROOT in backup_root.resolve().parents:
        raise RuntimeError("Backup must be outside the repository")
    settings = Settings.from_env()
    dsn = settings.require_database_url()
    url = urlsplit(dsn)
    project = urlsplit(settings.require_supabase_url()).hostname.split(".")[0]
    if project not in (url.hostname or "") + (url.username or ""):
        raise RuntimeError("Target project mismatch")
    if existing:
        folder = existing.resolve()
        if not folder.is_relative_to(backup_root.resolve()):
            raise RuntimeError("Existing archive must be within the authorized backup root")
    else:
        folder = backup_root / datetime.now(ZoneInfo("Asia/Singapore")).strftime("pre027-%Y%m%d-%H%M%S")
        folder.mkdir(parents=True, exist_ok=False)
        if os.name == "nt":
            sid = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "[Security.Principal.WindowsIdentity]::GetCurrent().User.Value",
                ],
                text=True,
            ).strip()
            subprocess.run(
                ["icacls", str(folder), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
                check=True,
                capture_output=True,
            )
        else:
            folder.chmod(0o700)
    bin_path = ROOT / "outputs/pg-local/pgsql/bin"

    def exe(name):
        return str(bin_path / (name + (".exe" if os.name == "nt" else "")))

    env = {
        **os.environ,
        "PGHOST": url.hostname,
        "PGPORT": str(url.port or 5432),
        "PGUSER": unquote(url.username or ""),
        "PGPASSWORD": unquote(url.password or ""),
        "PGDATABASE": url.path.lstrip("/") or "postgres",
        "PGSSLMODE": "require",
        "PGOPTIONS": "-c default_transaction_read_only=on -c statement_timeout=120000",
    }
    if existing:
        report = json.loads((folder / "backup-manifest.json").read_text(encoding="utf-8"))
        if report["project_fingerprint"] != hashlib.sha256(project.encode()).hexdigest()[:12]:
            raise RuntimeError("Archive target mismatch")
        if report["archive_sha256"] != hashlib.sha256((folder / "database.dump").read_bytes()).hexdigest():
            raise RuntimeError("Archive content changed")
    else:
        report = {
            "mode": "Owner-authorized READ ONLY production backup; private local restore",
            "private_folder": str(folder),
            "project_fingerprint": hashlib.sha256(project.encode()).hexdigest()[:12],
            "production_writes": False,
        }

    def command(args, filename, command_env=env):
        with (folder / filename).open("wb") as out:
            result = subprocess.run(args, env=command_env, stdout=out, stderr=subprocess.STDOUT, timeout=300)
        if result.returncode:
            raise RuntimeError(f"Official tool failed ({Path(args[0]).name}); private log retained")

    if existing:
        expected = json.loads((folder / "fingerprints.json").read_text(encoding="utf-8"))
        roles = [
            (name.strip('"'),)
            for name in re.findall(r"^CREATE ROLE ([^;]+);", (folder / "roles.sql").read_text(encoding="utf-8"), re.M)
        ]
    else:
        with psycopg.connect(dsn, connect_timeout=12, autocommit=True) as source:
            source.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            source.execute("SET LOCAL TIME ZONE 'UTC'")
            source.execute("SET LOCAL statement_timeout='120s'")
            snapshot = source.execute("SELECT pg_export_snapshot()").fetchone()[0]
            report["server_version"] = source.execute("SHOW server_version").fetchone()[0]
            command(
                [
                    exe("pg_dump"),
                    "--no-password",
                    "--format=custom",
                    "--snapshot",
                    snapshot,
                    "--file",
                    str(folder / "database.dump"),
                ],
                "dump.log",
            )
            command(
                [
                    exe("pg_dumpall"),
                    "--no-password",
                    "--roles-only",
                    "--no-role-passwords",
                    "--file",
                    str(folder / "roles.sql"),
                ],
                "roles.log",
            )
            expected = fingerprints(source)
            roles = source.execute("SELECT rolname FROM pg_roles WHERE rolname NOT LIKE 'pg_%'").fetchall()
            (folder / "fingerprints.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
        command([exe("pg_restore"), "--list", str(folder / "database.dump")], "archive-toc.txt")
        report["archive_sha256"] = hashlib.sha256((folder / "database.dump").read_bytes()).hexdigest()
        report["archive_bytes"] = (folder / "database.dump").stat().st_size
        report["archive_readable"] = True
        report["roles_without_passwords"] = True
        (folder / "backup-manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "backup_created": True,
                    "archive_readable": True,
                    "bytes": report["archive_bytes"],
                    "private_folder": str(folder),
                }
            ),
            flush=True,
        )
    archive_folder = folder
    folder = archive_folder / datetime.now(ZoneInfo("Asia/Singapore")).strftime("restore-check-%H%M%S")
    folder.mkdir(exist_ok=False)
    password = secrets.token_urlsafe(32)
    pwfile = folder / "restore.pw"
    pwfile.write_text(password, encoding="utf-8")
    command(
        [
            exe("initdb"),
            "-D",
            str(folder / "restore-data"),
            "-U",
            "postgres",
            "--auth=scram-sha-256",
            "--pwfile",
            str(pwfile),
        ],
        "initdb.log",
        os.environ.copy(),
    )
    pwfile.unlink()
    local_env = {
        **os.environ,
        "PGHOST": "127.0.0.1",
        "PGPORT": "55441",
        "PGDATABASE": "postgres",
        "PGUSER": "postgres",
        "PGPASSWORD": password,
        "PGSSLMODE": "disable",
        "PGOPTIONS": "-c timezone=UTC",
    }
    with (folder / "postgres.log").open("wb") as log:
        process = subprocess.Popen(
            [exe("postgres"), "-D", str(folder / "restore-data"), "-p", "55441", "-h", "127.0.0.1"],
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    try:
        local = None
        for _ in range(40):
            if process.poll() is not None:
                raise RuntimeError("Private restore instance could not start")
            try:
                local = psycopg.connect(
                    host="127.0.0.1",
                    port=55441,
                    dbname="postgres",
                    user="postgres",
                    password=password,
                    autocommit=True,
                    connect_timeout=1,
                )
                break
            except psycopg.OperationalError:
                time.sleep(0.25)
        if local is None:
            raise RuntimeError("Private restore startup timed out")
        with local:
            for (role,) in roles:
                if role != "postgres":
                    local.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
            local.execute("CREATE SCHEMA extensions")
            local.execute("CREATE SCHEMA auth")
            local.execute("CREATE SCHEMA storage")
            for extension in ["pgcrypto", "uuid-ossp"]:
                local.execute(sql.SQL("CREATE EXTENSION {} WITH SCHEMA extensions").format(sql.Identifier(extension)))
            command(
                [
                    exe("pg_restore"),
                    "--exit-on-error",
                    "--no-owner",
                    "--schema=auth",
                    "--schema=storage",
                    "--schema=public",
                    "--dbname=postgres",
                    str(archive_folder / "database.dump"),
                ],
                "restore.log",
                local_env,
            )
            local.execute("SET TIME ZONE 'UTC'")
            actual = fingerprints(local)
            report["restored_table_count"] = len(actual)
            report["all_table_row_counts_and_digests_match"] = actual == expected
            report["restore_scope"] = (
                "public + auth + storage Schema/data/grants; managed roles represented by NOLOGIN local roles"
            )
            if actual != expected:
                raise RuntimeError("Restored row integrity differs")
            report["restore_verified"] = True
            (archive_folder / "backup-manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    finally:
        subprocess.run(
            [exe("pg_ctl"), "stop", "-D", str(folder / "restore-data"), "-m", "fast", "-t", "15"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        process.wait(timeout=20)
    report["limits"] = (
        "No Storage object bytes, platform configuration/PITR or secret recovery promise. "
        "Full archive is retained; non-application managed schemas were not restored."
    )
    Path("outputs/release/backup-verification-20261019.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {"restore_verified": True, "table_count": report["restored_table_count"], "all_digests_match": True}
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorized-production-backup", required=True, action="store_true")
    parser.add_argument("--backup-root", required=True, type=Path)
    parser.add_argument("--verify-existing", type=Path)
    args = parser.parse_args()
    try:
        run(args.backup_root, args.verify_existing)
    except Exception as error:
        # Tool logs may contain patient rows; never relay them to chat/repo.
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "error_type": type(error).__name__,
                    "detail": "Private tool logs retained outside repository; no production write performed",
                }
            )
        )
        raise SystemExit(2) from None
