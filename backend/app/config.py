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

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ENV_FILE_VARIABLE = "PHARMASCAN_ENV_FILE"
DEFAULT_ENV_FILE = ".env"


class ConfigError(RuntimeError):
    """Raised when a required setting is missing.

    The message contains the variable NAME only — never a value.
    """


def validate_publishable_key(value: str) -> str:
    """Reject secret/service-role keys even when stored under a public key name."""
    if value.startswith("sb_secret_"):
        raise ConfigError("SUPABASE_PUBLISHABLE_KEY must not contain a secret key")
    if value.count(".") == 2:
        try:
            encoded = value.split(".")[1]
            payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            if not isinstance(payload, dict) or payload.get("role") != "anon":
                raise ConfigError("SUPABASE_PUBLISHABLE_KEY must use the legacy anon role")
        except (ValueError, UnicodeDecodeError):
            raise ConfigError("SUPABASE_PUBLISHABLE_KEY has invalid legacy key metadata") from None
    return value


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

    database_url: str | None = field(repr=False)
    supabase_url: str | None = field(repr=False)
    supabase_publishable_key: str | None = field(repr=False)
    supabase_secret_key: str | None = field(repr=False)
    app_env: str
    app_origin: str | None
    vision_api_base_url: str | None
    enable_demo_seed: bool
    persistence: str
    auth_mode: str
    source: str
    model_provider: str = "deterministic"
    gemini_api_key: str | None = field(default=None, repr=False)
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_thinking_level: str = "low"
    demo_agent_daily_turn_limit: int = 20
    enable_web_push: bool = False
    enable_push_subscriptions: bool = False
    enable_medication_library_files: bool = False
    enable_late_dose_reports: bool = False
    enable_multiple_care_reminders: bool = False
    enable_care_task_followups: bool = False
    vapid_public_key: str | None = field(default=None, repr=False)
    vapid_private_key: str | None = field(default=None, repr=False)
    vapid_subject: str | None = field(default=None, repr=False)
    push_dispatch_token: str | None = field(default=None, repr=False)
    tts_provider: str = "browser"
    stt_provider: str = "browser"
    enable_speech: bool = False
    tencent_speech_approved: bool = False
    tencent_secret_id: str | None = field(default=None, repr=False)
    tencent_secret_key: str | None = field(default=None, repr=False)
    tencent_voice_type: int | None = None
    tencent_speech_site: str = "domestic"

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

        stt_provider = read("STT_PROVIDER") or "browser"
        if stt_provider not in {"browser", "tencent"}:
            raise ConfigError("STT_PROVIDER must be browser or tencent")
        tts_provider = (read("TTS_PROVIDER") or "browser").strip().lower()
        if tts_provider not in {"browser", "tencent"}:
            raise ConfigError("TTS_PROVIDER must be browser or tencent")
        model_provider = (read("MODEL_PROVIDER") or "deterministic").lower()
        if model_provider not in {"deterministic", "gemini"}:
            raise ConfigError("MODEL_PROVIDER must be deterministic or gemini")
        if (read("GEMINI_THINKING_LEVEL") or "low") != "low":
            raise ConfigError("GEMINI_THINKING_LEVEL must be low for this demo")
        limit = read("DEMO_AGENT_DAILY_TURN_LIMIT") or "20"
        if not limit.isdigit() or not 1 <= int(limit) <= 20:
            raise ConfigError("DEMO_AGENT_DAILY_TURN_LIMIT must be 1..20")
        voice_type = read("TENCENT_TTS_VOICE_TYPE")
        if voice_type is not None and not voice_type.isdigit():
            raise ConfigError("TENCENT_TTS_VOICE_TYPE must be a numeric provider voice ID")
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
            model_provider=model_provider,
            gemini_api_key=read("GEMINI_API_KEY"),
            gemini_model=read("GEMINI_MODEL") or "gemini-3.5-flash-lite",
            demo_agent_daily_turn_limit=int(limit),
            enable_web_push=(read("ENABLE_WEB_PUSH") or "").lower() in {"1", "true", "yes"},
            enable_push_subscriptions=(read("ENABLE_PUSH_SUBSCRIPTIONS") or "").lower() in {"1", "true", "yes"},
            enable_medication_library_files=(read("ENABLE_MEDICATION_LIBRARY_FILES") or "").lower()
            in {"1", "true", "yes"},
            enable_multiple_care_reminders=(read("ENABLE_MULTIPLE_CARE_REMINDERS") or "").lower()
            in {"1", "true", "yes"},
            enable_care_task_followups=(read("ENABLE_CARE_TASK_FOLLOWUPS") or "").lower() in {"1", "true", "yes"},
            enable_late_dose_reports=(read("ENABLE_LATE_DOSE_REPORTS") or "").lower() in {"1", "true", "yes"},
            vapid_public_key=read("VAPID_PUBLIC_KEY"),
            vapid_private_key=read("VAPID_PRIVATE_KEY"),
            vapid_subject=read("VAPID_SUBJECT"),
            push_dispatch_token=read("PUSH_DISPATCH_TOKEN"),
            tts_provider=tts_provider,
            stt_provider=stt_provider,
            enable_speech=(read("ENABLE_SPEECH") or "").lower() in {"1", "true", "yes"},
            tencent_speech_approved=(read("TENCENT_SPEECH_APPROVED") or "").lower() in {"1", "true", "yes"},
            tencent_secret_id=read("TENCENT_SECRET_ID"),
            tencent_secret_key=read("TENCENT_SECRET_KEY"),
            tencent_voice_type=int(voice_type) if voice_type else None,
            tencent_speech_site=read("TENCENT_SPEECH_SITE") or "domestic",
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
        return validate_publishable_key(self.supabase_publishable_key)
