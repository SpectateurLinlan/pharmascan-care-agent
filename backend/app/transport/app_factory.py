"""FastAPI application factory.

The app is assembled here: one container, one error-handler table, CORS for
local development only. No route module imports a repository directly.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..domain.errors import DomainError
from .container import ApplicationContainer, build_container
from .error_mapping import domain_error_handler
from .routes import agent as agent_routes
from .routes import demo as demo_routes
from .routes import doses as dose_routes
from .routes import health as health_routes
from .routes import medications as medication_routes

LOGGER = logging.getLogger("pharmascan.transport")


def create_app(container: ApplicationContainer | None = None) -> FastAPI:
    """Build the ASGI app. Pass a container to inject a test double."""
    app = FastAPI(
        title="PharmaScan Care Agent API",
        version="0.1.0",
        description=(
            "Minimum user-facing API for the PharmaScan Care hackathon demo. "
            "SIMULATED persistence (in-memory) and degraded-mode agent routing; "
            "no live LLM and no live Stage2 vision provider in this build."
        ),
    )

    wired = container or build_container()
    app.state.container = wired

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    app.add_exception_handler(DomainError, domain_error_handler)

    app.include_router(health_routes.router)
    app.include_router(demo_routes.router)
    app.include_router(medication_routes.router)
    app.include_router(dose_routes.router)
    app.include_router(agent_routes.router)

    LOGGER.info("PharmaScan Care transport created (SIMULATED persistence)")
    return app
