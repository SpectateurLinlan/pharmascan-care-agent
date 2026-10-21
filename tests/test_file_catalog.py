"""The maintained index must preserve manual explanations and exclude secrets/dependencies."""

import importlib.util
import json
from pathlib import Path


def test_generator_preserves_manual_metadata_and_never_extracts_private_content(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/maintenance/update_file_catalog.py"
    spec = importlib.util.spec_from_file_location("file_catalog", path)
    catalog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalog)
    monkeypatch.setattr(catalog, "ROOT", tmp_path)
    for folder in ["backend", "docs", "internal/docs", "outputs", "frontend/node_modules/pkg"]:
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    metadata = {"backend/entry.py": {"purpose": "manually verified purpose", "related": "test_entry.py"}}
    (tmp_path / "internal/docs/file_catalog_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (tmp_path / "backend/entry.py").write_text(
        '"""Automatically detected docstring."""\ndef run(): pass', encoding="utf-8"
    )
    (tmp_path / ".env").write_text("SECRET=do-not-export", encoding="utf-8")
    (tmp_path / "outputs/private.py").write_text('"""do-not-export"""', encoding="utf-8")
    (tmp_path / "frontend/node_modules/pkg/vendor.js").write_text("vendor", encoding="utf-8")
    content, rows = catalog.generate()
    assert "manually verified purpose" in content and "test_entry.py" in content
    assert "do-not-export" not in content + json.dumps(rows)
    assert not any(row["path"].endswith((".env", "vendor.js")) for row in rows)
    assert json.loads((tmp_path / "internal/docs/file_catalog_metadata.json").read_text()) == metadata
    assert catalog.generate() == (content, rows)


def test_default_scope_and_full_inventory_are_separate_repeatable_and_private(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/maintenance/update_file_catalog.py"
    spec = importlib.util.spec_from_file_location("file_catalog_scopes", path)
    catalog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalog)
    monkeypatch.setattr(catalog, "ROOT", tmp_path)
    for rel in [
        "backend/entry.py",
        "internal/docs/archive/source.md",
        "internal/backups/original.md",
        "outputs/retained.md",
        "evidence/original.md",
        "status/WORK_LOG.md",
        "outputs/private.p12",
        "outputs/private.pfx",
        "outputs/.env.local",
        "outputs/__pycache__/module.pyc",
        "outputs/node_modules/pkg/file.js",
    ]:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("private-content-must-not-be-extracted", encoding="utf-8")
    default_content, default_rows = catalog.generate()
    full_content, full_rows = catalog.generate(full=True)
    default_paths = {row["path"] for row in default_rows}
    full_paths = {row["path"] for row in full_rows}
    assert "internal/docs/archive/source.md" in default_paths
    retained = {"internal/backups/original.md", "outputs/retained.md", "evidence/original.md", "status/WORK_LOG.md"}
    assert default_paths.isdisjoint(retained)
    assert retained <= full_paths
    assert not any("private-content-must-not-be-extracted" in row["purpose"] for row in full_rows)
    assert not any(path.endswith((".p12", ".pfx", ".pyc", ".local", "file.js")) for path in full_paths)
    assert catalog.main([]) == 0
    assert catalog.main(["--check"]) == 0
    default_json = (tmp_path / "internal/docs/file_index.json").read_bytes()
    assert catalog.main(["--full"]) == 0
    assert catalog.main(["--full", "--check"]) == 0
    assert (tmp_path / "internal/docs/file_index.json").read_bytes() == default_json
    assert catalog.generate() == (default_content, default_rows)
    assert catalog.generate(full=True) == (full_content, full_rows)


def test_check_detects_missing_or_stale_catalog_without_writing(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/maintenance/update_file_catalog.py"
    spec = importlib.util.spec_from_file_location("file_catalog_check", path)
    catalog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalog)
    monkeypatch.setattr(catalog, "ROOT", tmp_path)
    assert catalog.main(["--check"]) == 1
    assert not (tmp_path / "internal").exists()
    assert catalog.main([]) == 0
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/added.md").write_text("# New source\n", encoding="utf-8")
    original = (tmp_path / "internal/docs/file_index.json").read_bytes()
    assert catalog.main(["--check"]) == 1
    assert (tmp_path / "internal/docs/file_index.json").read_bytes() == original
    assert catalog.main([]) == 0
    assert catalog.main(["--check"]) == 0
