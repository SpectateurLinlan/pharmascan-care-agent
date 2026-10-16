"""Render patient API composition root; never starts the privileged dispatcher.

Run --check-resources during build. Normal startup reads process environment
only, validates deployment boundaries, then serves the existing FastAPI app.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import ConfigError, Settings  # noqa: E402
from app.infrastructure.stage2_schema import Stage2Contract  # noqa: E402


def check_resources(root: Path) -> None:
    """Check the source checkout layout used by the existing Stage2 adapters."""
    snapshot = root / "docs/external/pharmascan-api-openapi-0.10.0.json"
    if not snapshot.is_file():
        raise ConfigError("Required Stage2 contract resource is missing")
    contract = Stage2Contract(json.loads(snapshot.read_text(encoding="utf-8")))
    if contract.version != "0.10.0":
        raise ConfigError("Patient deployment requires Stage2 contract 0.10.0")
    # Import runtime dependencies without constructing clients or making calls.
    import google.genai  # noqa: F401
    import PIL.Image  # noqa: F401
    import psycopg  # noqa: F401
    import pywebpush  # noqa: F401
    import uvicorn  # noqa: F401
    from app.transport.app_factory import create_app  # noqa: F401


def check_settings(settings: Settings) -> None:
    """Fail closed for this initial Render deployment; no worker credentials."""
    if settings.auth_mode != "supabase" or settings.persistence != "supabase":
        raise ConfigError("Patient deployment requires AUTH_MODE=supabase and PERSISTENCE=supabase")
    if settings.enable_demo_seed:
        raise ConfigError("Patient deployment requires ENABLE_DEMO_SEED=false")
    for name, value in (
        ("DATABASE_URL", settings.database_url),
        ("SUPABASE_SECRET_KEY", settings.supabase_secret_key),
        ("PUSH_DISPATCH_TOKEN", settings.push_dispatch_token),
        ("VAPID_PRIVATE_KEY", settings.vapid_private_key),
    ):
        if value:
            raise ConfigError(f"{name} must not be configured on this patient API service")
    if settings.enable_web_push:
        raise ConfigError("Initial Render deployment requires ENABLE_WEB_PUSH=false; push needs separate acceptance")
    if settings.enable_speech or settings.tts_provider != "browser" or settings.stt_provider != "browser":
        raise ConfigError("Initial Render deployment requires browser speech with ENABLE_SPEECH=false")
    for name, value in (
        ("APP_ORIGIN", settings.app_origin),
        ("SUPABASE_URL", settings.supabase_url),
        ("VISION_API_BASE_URL", settings.vision_api_base_url),
    ):
        parsed = urlsplit(value or "")
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or (name == "APP_ORIGIN" and parsed.path != "")
        ):
            raise ConfigError(f"{name} requires an HTTPS URL without credentials, query or fragment")
    settings.require_publishable_key()
    if settings.model_provider == "gemini" and not settings.gemini_api_key:
        raise ConfigError("GEMINI_API_KEY is required when MODEL_PROVIDER=gemini")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-resources", action="store_true")
    args = parser.parse_args()
    try:
        check_resources(REPO_ROOT)
        if args.check_resources:
            print("Patient runtime imports and Stage2 0.10.0 resource: PASS (no provider calls)")
            return 0
        # Do not import a developer's dotenv file, including its admin DB key.
        settings = Settings.from_env(env_file=Path(os.devnull))
        check_settings(settings)
        port_text = os.environ.get("PORT", "10000")
        if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
            raise ConfigError("PORT must be an integer from 1 to 65535")
    except (ConfigError, ValueError, OSError, ImportError) as exc:
        # Configuration errors above contain names only; never print provider values.
        message = str(exc) if isinstance(exc, ConfigError) else type(exc).__name__
        print(f"Patient deployment check failed: {message}", file=sys.stderr)
        return 2

    import uvicorn
    from app.transport.app_factory import create_app

    uvicorn.run(
        create_app(settings=settings),
        host="0.0.0.0",
        port=int(port_text),
        workers=1,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=30,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
