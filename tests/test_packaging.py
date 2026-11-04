"""Regression checks for the repository's Python packaging boundary."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_setuptools_discovers_only_the_backend_app_namespace() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert config["build-system"] == {
        "requires": ["setuptools>=68"],
        "build-backend": "setuptools.build_meta",
    }
    assert config["tool"]["setuptools"]["package-dir"] == {"": "backend"}
    assert config["tool"]["setuptools"]["packages"]["find"] == {
        "where": ["backend"],
        "include": ["app*"],
        "namespaces": True,
    }


def test_built_wheel_contains_loadable_versioned_name_resource(tmp_path) -> None:
    # Build from an isolated source copy. No installs, build isolation or network.
    shutil.copy2(ROOT / "pyproject.toml", tmp_path)
    shutil.copytree(ROOT / "backend/app", tmp_path / "backend/app", ignore=shutil.ignore_patterns("__pycache__"))
    builder = os.environ.get("MEDITHREAD_PACKAGING_PYTHON", sys.executable)
    probe = subprocess.run([builder, "-c", "import setuptools"], capture_output=True, timeout=20)
    if probe.returncode and builder == sys.executable:
        pytest.skip("setuptools build environment unavailable; set MEDITHREAD_PACKAGING_PYTHON explicitly")
    assert probe.returncode == 0, "Explicit packaging Python must provide setuptools"
    result = subprocess.run(
        [builder, "-c", "from setuptools.build_meta import build_wheel; build_wheel('dist')"],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    with zipfile.ZipFile(next((tmp_path / "dist").glob("*.whl"))) as wheel:
        resource = json.loads(wheel.read("app/resources/medication_aliases.v1.json"))
        assert resource["version"] == 1
        assert any(row["canonical_name"] == "IBUPROFEN" and row["reviewed"] for row in resource["entries"])
        assert "app/resources/__init__.py" in wheel.namelist()
