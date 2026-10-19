"""Vercel-only entrypoint for the isolated notification dispatcher project."""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
_backend = str(_root / "backend")
if _backend not in sys.path:
    sys.path.insert(0, _backend)

from app.config import Settings  # noqa: E402
from app.infrastructure.dispatch_process import ProcessDispatchRunner  # noqa: E402
from app.transport.dispatcher import create_dispatcher_app  # noqa: E402

# Entry location is explicit in pyproject.toml; worker resources remain rooted
# in the same checkout/bundle, independent of the caller's working directory.
_settings = Settings.from_env()
app = create_dispatcher_app(
    settings=_settings,
    runner=ProcessDispatchRunner(root=_root),
    synthetic_runner=ProcessDispatchRunner(root=_root, synthetic_only=True)
    if _settings.push_synthetic_patient_id
    else None,
)
