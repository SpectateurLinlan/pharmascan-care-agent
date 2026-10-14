"""Health and capability endpoints.

``/api/health`` deliberately reports what is real and what is simulated. It
never returns "ok" for a dependency that is not actually wired.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    container = request.app.state.container
    return HealthResponse(
        database=container.persistence,
        stage2_vision="live" if container.visual_check else "simulated",
        llm="gemini_configured" if container.conversational_model else "unavailable_deterministic_degraded",
    )
