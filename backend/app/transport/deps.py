"""Per-request dependency access.

Routes must not import a container constructor; they ask for one here. The
container lives on ``app.state`` so tests can inject a deterministic clock.

``get_principal`` is the single place a route obtains a patient identity. It
resolves the authenticated context (verified Supabase JWT, or the explicitly
unauthenticated demo principal) and hands the route a ``patient_id`` that came
from that context — never from the request body and never from the agent.
"""

from __future__ import annotations

from dataclasses import replace

from fastapi import Query, Request

from ..contracts.workflow_runtime import unavailable_admission
from ..domain.errors import ProviderUnavailableError
from ..timing import timed_stage
from .auth import AuthenticatedPrincipal
from .container import ApplicationContainer


def get_container(request: Request) -> ApplicationContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:  # pragma: no cover - defensive, app_factory always sets it
        raise RuntimeError("application container is not configured")
    if container.patient_factory is not None:
        scoped = getattr(request.state, "patient_container", None)
        if scoped is None:
            principal = get_principal(request, request.query_params.get("client_id"))
            with timed_stage("compose"):
                scoped = container.patient_factory(principal)
            request.state.patient_container = scoped
        return _admit_request(request, scoped)
    return container


def _admit_request(request: Request, scoped: ApplicationContainer) -> ApplicationContainer:
    """Admission is technical readiness; existing services still authorize writes."""
    unsafe = request.method not in {"GET", "HEAD", "OPTIONS"}
    bound = unsafe and any(name in request.headers for name in ("x-assistant-task", "x-assistant-revision"))
    workflow = request.url.path.startswith("/api/agent/workflows/")
    capabilities = request.url.path == "/api/agent/workflows/capabilities"
    conversation = request.url.path == "/api/agent/messages" and unsafe
    native = bool(
        unsafe
        and scoped.assistant_runtime
        and scoped.assistant_runtime.native_media_enabled
        and (
            request.url.path.startswith("/api/evidence/") or request.url.path.startswith("/api/medications/unfinished/")
        )
    )
    if not (workflow or conversation or bound or native):
        return scoped
    if native and not scoped.assistant_candidate and not bound and not workflow:
        # The approved native bridge is independently usable. It keeps the
        # existing verified native services and never enables Assistant tools.
        status = getattr(request.state, "native_media_admission", None)
        if status is None:
            status = scoped.assistant_runtime.check()
            request.state.native_media_admission = status
        if not status.available:
            raise ProviderUnavailableError(
                "Assistant persistence is unavailable; existing input has not been submitted"
            )
        return scoped
    if not getattr(request.state, "workflow_admission_checked", False):
        candidate = scoped.assistant_candidate
        runtime = scoped.assistant_runtime
        status = runtime.check() if runtime and candidate else unavailable_admission("feature_disabled")
        if status.available and (
            candidate.container.assistant_workflows is None
            or scoped.assistant_transactions is None
            or candidate.ports.tasks is not scoped.assistant_transactions.tasks
        ):
            status = unavailable_admission("incomplete_capabilities")
        if status.available:
            scoped = replace(
                candidate.container,
                assistant_runtime=runtime,
                assistant_admission=status,
                assistant_execution=candidate.container.assistant_execution if runtime.progress_enabled else None,
            )
            request.state.patient_container = scoped
        else:
            scoped.assistant_admission = status
        request.state.workflow_admission_checked = True
    if (bound or native or (workflow and not capabilities)) and not scoped.assistant_admission.available:
        raise ProviderUnavailableError("Assistant persistence is unavailable; existing input has not been submitted")
    return scoped


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
    existing = getattr(request.state, "principal", None)
    if existing is not None:
        return existing
    container = request.app.state.container
    with timed_stage("auth"):
        principal = container.auth.resolve(
            authorization=request.headers.get("authorization"),
            client_id=client_id,
        )
    request.state.principal = principal
    return principal


__all__ = ["ApplicationContainer", "get_container", "get_principal"]
