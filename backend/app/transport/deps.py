"""Per-request dependency access.

Routes must not import a container constructor; they ask for one here. The
container lives on ``app.state`` so tests can inject a deterministic clock.

``get_principal`` is the single place a route obtains a patient identity. It
resolves the authenticated context (verified Supabase JWT, or the explicitly
unauthenticated demo principal) and hands the route a ``patient_id`` that came
from that context — never from the request body and never from the agent.
"""

from __future__ import annotations

from fastapi import Query, Request

from .auth import AuthenticatedPrincipal
from .container import ApplicationContainer


def get_container(request: Request) -> ApplicationContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:  # pragma: no cover - defensive, app_factory always sets it
        raise RuntimeError("application container is not configured")
    return container


def get_principal(
    request: Request,
    client_id: str | None = Query(
        default=None,
        min_length=1,
        max_length=128,
        description=(
            "Demo principal only. Ignored when AUTH_MODE=supabase, where the "
            "patient is taken from the verified bearer token instead."
        ),
    ),
) -> AuthenticatedPrincipal:
    """Resolve the acting patient for this request.

    Raises ``AUTH_REQUIRED`` when the configured mode cannot identify a patient,
    so an unauthenticated request can never reach a repository.
    """
    container = get_container(request)
    return container.auth.resolve(
        authorization=request.headers.get("authorization"),
        client_id=client_id,
    )


__all__ = ["ApplicationContainer", "get_container", "get_principal"]
