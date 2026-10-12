"""Per-request dependency access.

Routes must not import a container constructor; they ask for one here. The
container lives on ``app.state`` so tests can inject a deterministic clock.
"""

from __future__ import annotations

from fastapi import Request

from .container import ApplicationContainer


def get_container(request: Request) -> ApplicationContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:  # pragma: no cover - defensive, app_factory always sets it
        raise RuntimeError("application container is not configured")
    return container


__all__ = ["ApplicationContainer", "get_container"]
