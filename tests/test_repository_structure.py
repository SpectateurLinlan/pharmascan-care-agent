"""Offline layout checks: never import or run privileged maintenance tools."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MOVED_TOOLS = (
    "scripts/operations/db.py",
    "scripts/operations/create_vapid_keys.py",
    "scripts/qa/db_integration.py",
    "scripts/qa/stage2_contract_diff.py",
    "scripts/qa/stage2_v010_smoke.py",
    "scripts/fixtures/generate_gallery_demo.py",
)


@pytest.mark.parametrize("relative", MOVED_TOOLS)
def test_tools_resolve_resources_in_repository_without_execution(relative: str) -> None:
    script = ROOT / relative
    assert script.is_file(), f"Missing classified tool: {relative}"
    tree = ast.parse(script.read_text(encoding="utf-8"))
    roots = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "parents"
        and "__file__" in ast.unparse(node.value)
    ]
    assert roots, f"Tool must explicitly resolve its repository resources: {relative}"
    for node in roots:
        # Evaluate just the Path expression, never the script or its imports/main.
        actual = eval(compile(ast.Expression(node), relative, "eval"), {"Path": Path, "__file__": str(script)})
        assert actual == ROOT, f"{relative} would resolve resources outside the repository root"


def test_stable_launchers_and_backend_resource_paths_remain_available() -> None:
    for relative in (
        "scripts/start_dev.py", "scripts/run_patient_api.py", "scripts/run_reminders.py",
        "frontend/src/main.tsx", "frontend/src/app/App.tsx", "frontend/src/styles/index.css",
        "docs/external/pharmascan-api-openapi-0.10.0.json",
    ):
        assert (ROOT / relative).is_file(), relative


def test_src_root_contains_only_bootstrap_types_and_directory_guide() -> None:
    files = {p.name for p in (ROOT / "frontend/src").iterdir() if p.is_file()}
    assert files <= {"main.tsx", "vite-env.d.ts", "README.md"}, files
