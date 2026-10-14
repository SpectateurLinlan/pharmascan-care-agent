"""FastAPI application factory.

The app is assembled here: one container, one error-handler table, CORS for
local development only. No route module imports a repository directly.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import Settings
from ..domain.errors import DomainError
from .container import ApplicationContainer, build_container_from_settings
from .error_mapping import domain_error_handler
from .routes import agent as agent_routes
from .routes import caregivers as caregiver_routes
from .routes import demo as demo_routes
from .routes import doses as dose_routes
from .routes import evidence as evidence_routes
from .routes import feedback as feedback_routes
from .routes import health as health_routes
from .routes import medications as medication_routes
from .routes import patient_records as patient_record_routes
from .routes import preferences as preference_routes
from .routes import reminders as reminder_routes
from .routes import sources as source_routes
from .routes import speech as speech_routes
from .routes import usage as usage_routes
from .routes import visual as visual_routes

LOGGER = logging.getLogger("pharmascan.transport")


def create_app(container: ApplicationContainer | None = None, settings: Settings | None = None) -> FastAPI:
    """Build the ASGI app. Pass a container to inject a test double."""
    app = FastAPI(
        title="PharmaScan Care Agent API",
        version="0.1.0",
        description=(
            "Minimum user-facing API for the PharmaScan Care hackathon demo. "
            "Persistence and agent routing are reported honestly per response; "
            "configured Gemini tools and Stage2 visual evidence preserve deterministic safety and user RLS."
        ),
    )

    effective_settings = settings or (Settings.from_env() if container is None else None)
    wired = container or build_container_from_settings(effective_settings)
    if wired.persistence == "postgres":
        raise ValueError("Administrative PostgreSQL containers cannot serve patient HTTP requests")
    app.state.container = wired

    configured_origin = effective_settings.app_origin if effective_settings is not None else None
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[configured_origin]
        if configured_origin
        else [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Speech-Consent", "X-Stage2-Consent", "X-Demo-Only"],
    )

    app.add_exception_handler(DomainError, domain_error_handler)

    app.include_router(health_routes.router)
    app.include_router(demo_routes.router)
    app.include_router(medication_routes.router)
    app.include_router(dose_routes.router)
    app.include_router(agent_routes.router)
    app.include_router(speech_routes.router)
    app.include_router(source_routes.router)
    app.include_router(reminder_routes.router)
    app.include_router(visual_routes.router)
    app.include_router(evidence_routes.router)
    app.include_router(preference_routes.router)
    app.include_router(usage_routes.router)
    app.include_router(feedback_routes.router)
    app.include_router(caregiver_routes.router)
    app.include_router(patient_record_routes.router)

    LOGGER.info("PharmaScan Care transport created (persistence=%s)", wired.persistence)
    return app
