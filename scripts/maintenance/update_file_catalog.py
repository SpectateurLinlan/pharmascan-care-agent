"""Generate objective first-party navigation without overwriting manual explanations.

Run from root: python scripts/maintenance/update_file_catalog.py [--check]
Local file reads only; no credentials, network, database or Git mutation.
Manual descriptions belong in docs/file_catalog_metadata.json, never generated Markdown.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP = {
    ".git",
    ".agents",
    ".codex",
    ".aws",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".vercel",
    "dist",
    "build",
    "coverage",
    "htmlcov",
    "pg-local",
    "npm-cache",
    "genai-test-deps",
    "knowledge-test-deps",
    "test-deps",
    "vercel-cli",
}
TOPS = {
    "backend",
    "frontend",
    "supabase",
    "scripts",
    "tests",
    "docs",
    "deploy",
    "assets",
    "evidence",
    "status",
    "internal",
    "outputs",
    ".github",
}
SECRET_NAMES = {".env", "credentials.json", "auth-state.json"}


def files():
    for folder, dirs, names in os.walk(ROOT):
        parent = Path(folder)
        relative = parent.relative_to(ROOT)
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in SKIP
            and not d.startswith(("launcher-reload-", "reload-check-", "vercel-"))
            and (parent != ROOT or d in TOPS)
        )
        for name in sorted(names):
            if (
                name in SECRET_NAMES
                or name.startswith(".env.")
                and name != ".env.example"
                or name.endswith(".env")
                or name.endswith((".log", ".pyc", ".tmp", ".bak", ".tsbuildinfo", ".key", ".pem"))
            ):
                continue
            path = parent / name
            if path.is_symlink() or not path.is_file():
                continue
            yield path, (relative / name).as_posix()


def describe(path: Path, rel: str):
    top = rel.split("/")[0]
    module = "/".join(rel.split("/")[:3]) if "/" in rel else "root/build"
    description = {
        "backend": "后端模块",
        "frontend": "前端界面或客户端模块",
        "supabase": "版本化数据库契约",
        "tests": "自动化或显式验收测试",
        "docs": "技术文档",
        "status": "历史/当前验收记录",
        "outputs": "本地生成的验收产物或历史快照",
        "internal": "私有维护资料",
        "assets": "界面资源",
        "evidence": "演示或提交证据",
        "scripts": "开发维护入口",
        "deploy": "部署入口及配置",
    }.get(top, "项目构建、许可或工程配置")
    entry, flags, dependencies = "", [], []
    text = ""
    # Never extract configuration values or private-operation contents into public docs.
    if path.suffix in {".py", ".ts", ".tsx", ".md"} and top not in {"internal", "outputs", "status", "evidence"}:
        text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".py" and text:
        try:
            tree = ast.parse(text)
            description = (ast.get_docstring(tree) or description).split("\n")[0][:160]
            entry = ", ".join(n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)))[:140]
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    dependencies.append(node.module.replace(".", "/"))
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_argument"
                ):
                    flags.extend(
                        a.value
                        for a in node.args
                        if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith("--")
                    )
        except SyntaxError:
            entry = "PARSE ERROR — inspect before use"
    elif path.suffix in {".ts", ".tsx"} and text:
        entry = ", ".join(re.findall(r"export (?:async )?(?:function|class|const|interface|type)\s+(\w+)", text))[:140]
        dependencies = re.findall(r"from ['\"]([^'\"]+)['\"]", text)
        comment = re.search(r"/\*\*\s*(.*?)\*/", text, re.S)
        labels = list(dict.fromkeys(re.findall(r'(?:title|aria-label)="([^"{}]+)"', text)))
        cases = re.findall(r"(?:test|it)\(['\"]([^'\"]+)", text)
        if comment:
            description = re.sub(r"\s*\*\s*|\s+", " ", comment[1]).strip()[:160]
        elif labels:
            description = "实际 UI 标题/区域：" + "；".join(labels[:4])
        elif cases:
            description = "实际测试场景：" + "；".join(cases[:2])
        elif entry:
            description += "：" + entry
    elif path.suffix == ".md" and text:
        heading = re.search(r"^#\s+(.+)", text, re.M)
        if heading:
            description = heading[1][:160]
    return {
        "path": rel,
        "purpose": description,
        "module": module,
        "type": path.suffix or "root/config",
        "entry": entry,
        "flags": flags,
        "dependencies": dependencies,
    }


def generate():
    metadata_path = ROOT / "docs/file_catalog_metadata.json"
    manual = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    rows = []
    for path, rel in files():
        row = describe(path, rel)
        row.update(manual.get(rel, {}))
        rows.append(row)
    rows.sort(key=lambda row: row["path"])
    groups = defaultdict(list)
    for row in rows:
        groups[row["path"].split("/")[0] if "/" in row["path"] else "root"].append(row)
    lines = [
        "# File Catalog — 自动文件目录",
        "",
        (
            "由 `python scripts/maintenance/update_file_catalog.py` "
            "更新。人工职责/风险说明保存在 [file_catalog_metadata.json](file_catalog_metadata.json)，不会被生成器覆盖。"
        ),
        (
            f"当前扫描 {len(rows)} 个第一方文件。包括源代码、测试、保留文档/证据；"
            "外部依赖、工具/模型/数据库二进制、缓存、构建输出、凭据和受限启动器临时目录不属于本目录。"
        ),
        (
            "公开提交前以 Git allowlist 为准；本地 `status/`、`internal/`、`outputs/` 的存在不意味着应提交。"
            "这里仅索引路径，不复制内部报告或患者数据。"
        ),
        "",
    ]
    for group, entries in sorted(groups.items()):
        lines += [f"## {group}", "", "| 文件 | 实际职责 | 模块 / 类型 | 入口、参数或关联 |", "|---|---|---|---|"]
        for row in entries:
            refs = row.get("related", row["entry"])
            if row["flags"]:
                refs += " · CLI: " + ", ".join(row["flags"])
            values = [
                f"[{row['path']}](<../{row['path']}>)",
                row["purpose"],
                f"{row['module']} · {row['type']}",
                refs or "—",
            ]
            lines.append("| " + " | ".join(str(v).replace("|", "\\|").replace("\n", " ") for v in values) + " |")
    lines += [
        "",
        "## 执行脚本与安全边界",
        "",
        "| 入口 | 何时及如何运行 | 副作用 / 凭据 | Git / 有效性 |",
        "|---|---|---|---|",
    ]
    for row in rows:
        if (row["path"].startswith(("scripts/", "internal/operations/")) or row.get("run")) and row["type"] in {
            ".py",
            ".ps1",
            ".sql",
        }:
            run = row.get("run", "按源码 CLI/说明运行；先阅读参数，禁止盲跑")
            effects = row.get("effects", "需核对具体入口；未审定脚本不作为发布命令")
            publication = row.get("publication", "第一方公共 scripts 可审查提交；internal 私有，不提交")
            publication += "；" + row.get("validity", "未逐个执行；先核对源码和当前环境")
            lines.append(f"| `{row['path']}` | {run} | {effects} | {publication} |")
    lines += ["", "相关功能导航：[Repository Guide](REPOSITORY_GUIDE.md)。客观索引使用 `--check` 检查是否过期。", ""]
    return "\n".join(lines), rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content, rows = generate()
    output = ROOT / "docs/FILE_CATALOG.md"
    index = ROOT / "docs/file_index.json"
    if args.check:
        current = output.exists() and output.read_text(encoding="utf-8") == content
        current = current and index.exists() and json.loads(index.read_text(encoding="utf-8")) == rows
        raise SystemExit(0 if current else 1)
    output.write_text(content, encoding="utf-8")
    index.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Indexed {len(rows)} first-party files")
