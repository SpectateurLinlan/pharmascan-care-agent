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
    for folder in ["backend", "docs", "outputs", "frontend/node_modules/pkg"]:
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    metadata = {"backend/entry.py": {"purpose": "manually verified purpose", "related": "test_entry.py"}}
    (tmp_path / "docs/file_catalog_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
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
    assert json.loads((tmp_path / "docs/file_catalog_metadata.json").read_text()) == metadata
    assert catalog.generate() == (content, rows)
