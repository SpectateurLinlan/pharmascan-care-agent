"""Conservative local consolidation. --apply deletes only proven duplicate backups
and installed-archive duplicates, and moves an explicit operations list.
Never stages Git or touches patient data.

Run from root: python scripts/maintenance/consolidate_repository.py [--apply]
Every resolved mutation target is checked against the workspace and recorded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUSH_FILES = (
    "execute_authorized_push_once.py",
    "push_binding_readonly.py",
    "push_current_http_readonly.py",
    "push_production_readonly.py",
    "push_scope_readonly.py",
    "PUSH_ONE_SHOT_PREPARED.sql",
)


def checked(path: Path) -> Path:
    resolved = path.resolve()
    if ROOT not in resolved.parents:
        raise ValueError("Mutation target is outside workspace")
    return resolved


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def consolidate(apply: bool):
    actions = []
    # Compare full normalized bytes, not names or timestamps.
    canonical = [p for p in ROOT.iterdir() if p.is_file() and p.name not in {".env"}]
    canonical += [p for p in (ROOT / "internal").iterdir() if p.is_file()]
    canonical += [p for p in (ROOT / "docs").rglob("*") if p.is_file()]
    by_content = {p.read_bytes().replace(b"\r\n", b"\n"): p for p in canonical if p.stat().st_size < 500000}
    reachable = subprocess.check_output(["git", "rev-list", "--objects", "--all"], cwd=ROOT).decode().splitlines()
    objects = {line.split(" ", 1)[0] for line in reachable}
    for path in sorted((ROOT / "internal/backups").rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        content = path.read_bytes().replace(b"\r\n", b"\n")
        oid = subprocess.check_output(["git", "hash-object", "--stdin"], input=content, cwd=ROOT).decode().strip()
        retained = by_content.get(content)
        if retained or oid in objects:
            actions.append(
                {
                    "action": "delete_duplicate_backup",
                    "path": str(path.relative_to(ROOT)),
                    "sha256": digest(path),
                    "retained": str(retained.relative_to(ROOT)) if retained else "reachable-git-blob:" + oid,
                }
            )
            if apply:
                checked(path).unlink()
    # Downloaded PostgreSQL archive is redundant only after byte equality of critical executables.
    archive = ROOT / "outputs/pg-local/postgres.zip"
    if archive.exists():
        with zipfile.ZipFile(archive) as z:
            names = ["pgsql/bin/postgres.exe", "pgsql/bin/initdb.exe", "pgsql/bin/pg_ctl.exe"]
            identical = all(z.read(name) == (ROOT / "outputs/pg-local" / name).read_bytes() for name in names)
        if identical:
            actions.append(
                {
                    "action": "delete_duplicate_archive",
                    "path": str(archive.relative_to(ROOT)),
                    "sha256": digest(archive),
                    "retained": "outputs/pg-local/pgsql; critical executables byte-equal",
                }
            )
            if apply:
                checked(archive).unlink()
    for name in PUSH_FILES:
        source, target = ROOT / "status" / name, ROOT / "internal/operations/push" / name
        if not source.exists():
            continue
        if target.exists():
            raise ValueError("Refusing to overwrite an operations file")
        actions.append(
            {
                "action": "move_private_operation",
                "path": str(source.relative_to(ROOT)),
                "target": str(target.relative_to(ROOT)),
                "sha256": digest(source),
            }
        )
        if apply:
            checked(target).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(checked(source)), str(checked(target)))
            if target.suffix == ".py":
                text = target.read_text(encoding="utf-8").replace(
                    "Path(__file__).resolve().parents[1]", "Path(__file__).resolve().parents[3]"
                )
                if name == "execute_authorized_push_once.py":
                    text = text.replace(
                        "if __name__ == '__main__':",
                        (
                            "if __name__ == '__main__':\n    import argparse\n"
                            "    parser = argparse.ArgumentParser(description=__doc__)\n    "
                            "parser.add_argument('--execute-production-once', action='store_true', required=True)\n"
                            "    parser.add_argument('--approval-reference', required=True)\n    parser.parse_args()"
                        ),
                    )
                target.write_text(text, encoding="utf-8")
    output = ROOT / "outputs/release/repository-cleanup.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"applied": apply, "actions": actions}, indent=2), encoding="utf-8")
    print(json.dumps({"applied": apply, "actions": len(actions)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    consolidate(parser.parse_args().apply)
