"""Validate an isolated test configuration offline; never prints credentials or connects."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import ConfigError, parse_env_file, validate_publishable_key  # noqa: E402


def validate_target(test: dict[str, str], production: dict[str, str]) -> str:
    """Require an explicitly named cloud test project, separate from the normal target."""
    if any(
        test.get(key) != value
        for key, value in {
            "APP_ENV": "test",
            "AUTH_MODE": "supabase",
            "PERSISTENCE": "supabase",
        }.items()
    ):
        raise ValueError("Explicit test runtime settings are required")
    ref = test.get("TEST_PROJECT_REF", "")
    host = urlparse(test.get("SUPABASE_URL", "")).hostname
    production_host = urlparse(production.get("SUPABASE_URL", "")).hostname
    if not production_host:
        raise ValueError("Normal project identity must be known before test writes")
    if not ref.isalnum() or host != f"{ref}.supabase.co" or host == production_host:
        raise ValueError("Test project must be explicit and different from the normal project")
    dsn = urlparse(test.get("DATABASE_URL", ""))
    if dsn.scheme not in {"postgres", "postgresql"}:
        raise ValueError("An explicit test database configuration is required")
    direct = dsn.hostname == f"db.{ref}.supabase.co" and dsn.username == "postgres"
    pooled = (
        (dsn.hostname or "").endswith(".pooler.supabase.com")
        and unquote(dsn.username or "") == f"postgres.{ref}"
        and dsn.port == 5432
    )
    if not direct and not pooled:
        raise ValueError("Database target does not match the explicit test project/session connection")
    if not test.get("SUPABASE_PUBLISHABLE_KEY") or test.get("SUPABASE_SECRET_KEY"):
        raise ValueError("Patient tests need a publishable key and no administrative API key")
    try:
        validate_publishable_key(test["SUPABASE_PUBLISHABLE_KEY"])
    except ConfigError:
        raise ValueError("Administrative or invalid patient API key refused") from None
    return hashlib.sha256(host.encode()).hexdigest()[:12]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        # Read files directly: process environment must never silently override
        # the staging identity with a production URL or token.
        fingerprint = validate_target(parse_env_file(args.env_file), parse_env_file(ROOT / ".env"))
    except (ValueError, OSError):
        print("BLOCKED: isolated configuration is missing or targets are inconsistent; no connection attempted")
        return 2
    print(f"PASS offline target separation; test fingerprint={fingerprint}; no connection attempted")
    print("The actual test runner must enforce the same targets and verify JWT issuer before every write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
