"""Local relocated-entry smoke; no provider, database or subprocess calls."""

import importlib
import json
import os
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient


def test_vercel_bundle_patterns_respect_public_schema_limits():
    """Vercel's public schema limits each bundle glob string to 256 chars."""
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "vercel.json").read_text(encoding="utf-8"))
    for function in config["functions"].values():
        for name in ("includeFiles", "excludeFiles"):
            assert isinstance(function[name], str)
            assert len(function[name]) <= 256, name


def test_vercel_custom_entry_from_other_cwd_is_dispatcher_only(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    config = json.loads((root / "vercel.json").read_text(encoding="utf-8"))
    module, attribute = project["tool"]["vercel"]["entrypoint"].split(":")
    entry = root / (module.replace(".", "/") + ".py")
    assert entry.is_file()
    assert entry.relative_to(root).as_posix() in config["functions"]
    monkeypatch.setenv("PHARMASCAN_ENV_FILE", os.devnull)
    monkeypatch.setenv("PUSH_DISPATCH_TOKEN", "DEMO-only-test-dispatch-secret-" + "x" * 32)
    monkeypatch.chdir(tmp_path)
    app = getattr(importlib.import_module(module), attribute)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/internal/notifications/dispatch").status_code == 401
        assert client.get("/api/me/preferences").status_code == 404
