"""Health and capability endpoints.

``/api/health`` deliberately reports what is real and what is simulated. It
never returns "ok" for a dependency that is not actually wired.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()
