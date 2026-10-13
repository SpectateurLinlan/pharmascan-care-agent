"""Environment-driven configuration with no secret leakage.

Design rules (AGENTS.md rule 2, docs/ARCHITECTURE.md):
- configuration is read once at a composition root and injected; nothing in
  domain/application imports this module;
- values are **never** logged, echoed, formatted into errors, or written to
  files. ``Settings.describe()`` deliberately returns booleans only, so a
  diagnostic report can prove a variable is present without exposing it;
- the loader reads the process environment first, then optionally one dotenv
  file named by ``PHARMASCAN_ENV_FILE`` (default ``.env``). The tracked
  ``.env.example`` is **not** a default source: a tracked file must never hold
  live credentials (see status/BLOCKERS.md B12).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_FILE_VARIABLE = "PHARMASCAN_ENV_FILE"
DEFAULT_ENV_FILE = ".env"


class ConfigError(RuntimeError):
    """Raised when a required setting is missing.

    The message contains the variable NAME only — never a value.
    """


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a minimal dotenv file: ``KEY=value``, ``#`` comments, no expansion."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        if not key:
            continue
        cleaned = value.strip()
        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
            cleaned = cleaned[1:-1]
        values[key] = cleaned
    return values


def resolve_env_file(explicit: Path | None = None) -> Path | None:
    """Return the dotenv file to load, or ``None`` when there is nothing to load."""
    if explicit is not None:
        return explicit
    configured = os.environ.get(ENV_FILE_VARIABLE)
    if configured:
        return Path(configured)
    default = Path(DEFAULT_ENV_FILE)
    return default if default.is_file() else None


@dataclass(frozen=True)
class Settings:
    """Immutable configuration snapshot."""

    database_url: str | None
    supabase_url: str | None
    supabase_publishable_key: str | None
    supabase_secret_key: str | None
    app_env: str
    app_origin: str | None
    vision_api_base_url: str | None
    enable_demo_seed: bool
    persistence: str
    auth_mode: str
    source: str

    # -- construction --------------------------------------------------------

    @classmethod
    def from_env(cls, *, env_file: Path | None = None) -> Settings:
        """Load settings from the process environment (optionally seeded by a file).

        A real environment variable always wins over the file, so CI/deploy can
        override a developer's local file without editing it.
        """
        path = resolve_env_file(env_file)
        file_values = parse_env_file(path) if path is not None else {}

        def read(name: str) -> str | None:
            value = os.environ.get(name)
            if value is None:
                value = file_values.get(name)
            if value is None:
                return None
            value = value.strip()
            return value or None

        return cls(
            database_url=read("DATABASE_URL"),
            supabase_url=read("SUPABASE_URL"),
            supabase_publishable_key=read("SUPABASE_PUBLISHABLE_KEY"),
            supabase_secret_key=read("SUPABASE_SECRET_KEY"),
            app_env=read("APP_ENV") or "local",
            app_origin=read("APP_ORIGIN"),
            vision_api_base_url=read("VISION_API_BASE_URL"),
            enable_demo_seed=(read("ENABLE_DEMO_SEED") or "").lower() in {"1", "true", "yes"},
            persistence=(read("PERSISTENCE") or "in_memory").strip().lower(),
            auth_mode=(read("AUTH_MODE") or "demo").strip().lower(),
            source=str(path) if path is not None else "process_environment",
        )

    # -- safe diagnostics ----------------------------------------------------

    def describe(self) -> dict[str, object]:
        """Presence report safe to print, log or attach to evidence.

        Booleans only — no length, prefix, suffix or hash of any value, so the
        report cannot be used to brute-force or fingerprint a credential.
        """
        return {
            "source": self.source,
            "app_env": self.app_env,
            "DATABASE_URL": self.database_url is not None,
            "SUPABASE_URL": self.supabase_url is not None,
            "SUPABASE_PUBLISHABLE_KEY": self.supabase_publishable_key is not None,
            "SUPABASE_SECRET_KEY": self.supabase_secret_key is not None,
            "APP_ORIGIN": self.app_origin is not None,
            "VISION_API_BASE_URL": self.vision_api_base_url is not None,
            "ENABLE_DEMO_SEED": self.enable_demo_seed,
            "PERSISTENCE": self.persistence,
            "AUTH_MODE": self.auth_mode,
        }

    # -- required settings ---------------------------------------------------

    def require_database_url(self) -> str:
        if not self.database_url:
            raise ConfigError(
                "DATABASE_URL is not configured; set the environment variable or "
                f"point {ENV_FILE_VARIABLE} at a local dotenv file"
            )
        return self.database_url

    def require_supabase_url(self) -> str:
        if not self.supabase_url:
            raise ConfigError("SUPABASE_URL is not configured")
        return self.supabase_url.rstrip("/")

    def require_publishable_key(self) -> str:
        if not self.supabase_publishable_key:
            raise ConfigError("SUPABASE_PUBLISHABLE_KEY is not configured")
        return self.supabase_publishable_key
