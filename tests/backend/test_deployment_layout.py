"""Local relocated-entry smoke; no provider, database or subprocess calls."""

import importlib
import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_frontend_has_independent_install_and_build_configuration():
    """The UI needs dev build tools and must not inherit the worker config."""
    root = Path(__file__).resolve().parents[2]
    frontend = root / "frontend"
    config = json.loads((frontend / "vercel.json").read_text(encoding="utf-8"))
    assert config["framework"] == "vite"
    assert config["installCommand"] == "npm ci --include=dev"
    assert config["buildCommand"] == "npm run build"
    assert config["outputDirectory"] == "dist"
    assert "functions" not in config
    package = json.loads((frontend / "package.json").read_text(encoding="utf-8"))
    assert "vite" in package["devDependencies"]
    assert (frontend / "package-lock.json").is_file()
    shared_rules = (root / ".vercelignore").read_text(encoding="utf-8").splitlines()
    assert "/*" in shared_rules
    assert "!/frontend/" in shared_rules
    assert "!/backend/app/" in shared_rules
    assert "!/deploy/dispatcher/" in shared_rules
    assert "!/scripts/run_reminders.py" in shared_rules
    assert "**/.*" in shared_rules
    private_rules = (frontend / ".vercelignore").read_text(encoding="utf-8").splitlines()
    assert {"/*", "!/src/", "!/public/", "!/package-lock.json", "**/.*"} <= set(private_rules)


def test_frontend_upload_rules_support_git_and_local_path_bases():
    """Check ignore semantics for both Git checkout paths and local UI uploads."""
    root = Path(__file__).resolve().parents[2]
    node = shutil.which("node")
    if not node or not (root / "frontend/node_modules/ignore").is_dir():
        pytest.skip("Requires Node and installed frontend development dependencies")
    result = subprocess.run(
        [node, str(root / "tests/check_vercel_inputs.cjs")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_frontend_proxies_api_without_spa_fallback_or_cache():
    """API errors must remain API responses; SPA fallback must exclude API paths."""
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "frontend/vercel.json").read_text(encoding="utf-8"))
    api_route, spa_route = config["rewrites"]
    assert api_route == {
        "source": "/api/:path*",
        "destination": "https://medithread-patient-api.onrender.com/api/:path*",
    }
    assert "?" not in api_route["destination"]  # Do not replace the incoming query.
    assert spa_route["destination"] == "/index.html"
    for path in ["/api", "/api/health", "/api/agent/history", "/api/nonexistent"]:
        assert re.fullmatch(spa_route["source"], path) is None
    for path in ["/", "/account", "/medicines/detail"]:
        assert re.fullmatch(spa_route["source"], path) is not None
    headers = {item["source"]: item["headers"] for item in config["headers"]}
    assert {"key": "Cache-Control", "value": "private, no-store"} in headers["/api/:path*"]
    assert {"key": "Cache-Control", "value": "no-cache"} in headers["/sw.js"]


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
