"""Regression checks for the repository's Python packaging boundary."""

from __future__ import annotations

import tomllib
from pathlib import Path

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
