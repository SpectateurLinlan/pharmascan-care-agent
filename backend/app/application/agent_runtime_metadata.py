"""Hashes and actual SDK usage only; never retain prompts or provider responses."""

import hashlib
import json
import re
from pathlib import Path

from ..contracts.agent_execution import ProviderUsage


def content_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def model_name(value: object) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9._/-]{1,100}", value) else None


def combine_usage(previous: ProviderUsage | None, actual: ProviderUsage) -> ProviderUsage:
    if previous is None:
        return actual
    return ProviderUsage(
        **{
            key: getattr(previous, key) + getattr(actual, key)
            if getattr(previous, key) is not None and getattr(actual, key) is not None
            else None
            for key in ProviderUsage.model_fields
        }
    )


def source_revision() -> str | None:
    """Read Git metadata without spawning commands; packaged builds may be unknown."""
    for parent in Path(__file__).resolve().parents:
        marker = parent / ".git"
        if marker.exists():
            try:
                gitdir = Path(marker.read_text().strip().removeprefix("gitdir: ")) if marker.is_file() else marker
                if not gitdir.is_absolute():
                    gitdir = parent / gitdir
                head = (gitdir / "HEAD").read_text().strip()
                if head.startswith("ref: "):
                    common = gitdir
                    if (gitdir / "commondir").exists():
                        common = gitdir / (gitdir / "commondir").read_text().strip()
                    head = (common / head[5:]).read_text().strip()
                return head if re.fullmatch(r"[a-f0-9]{40}", head) else None
            except (OSError, ValueError):
                return None
    return None


def runtime_hash() -> str | None:
    """Identify the actual application source, including uncommitted changes."""
    app_root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    try:
        for path in sorted(app_root.rglob("*.py")):
            digest.update(path.relative_to(app_root).as_posix().encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()
    except OSError:
        return None
