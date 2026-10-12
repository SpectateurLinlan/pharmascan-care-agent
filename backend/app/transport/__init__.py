"""HTTP transport layer (FastAPI).

This is the ONLY layer allowed to speak HTTP. It must not import
``infrastructure`` adapters beyond the composition root, and it never touches
SQL, ORM models or the database directly (AGENTS.md rules 1-3). Routes accept
typed request DTOs, delegate to application services / the agent orchestrator,
and map domain errors to stable error codes.
"""

from __future__ import annotations

__all__ = ["create_app"]


def create_app(*args, **kwargs):
    """Lazy re-export so importing ``app.transport`` never requires FastAPI."""
    from .app_factory import create_app as _create_app

    return _create_app(*args, **kwargs)
