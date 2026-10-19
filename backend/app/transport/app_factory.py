"""FastAPI application factory.

The app is assembled here: one container, one error-handler table, CORS for
local development only. No route module imports a repository directly.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

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
from .routes import late_reports as late_report_routes
from .routes import long_term as long_term_routes
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
    effective_settings = settings or (Settings.from_env() if container is None else None)
    wired = container or build_container_from_settings(effective_settings)
    if wired.persistence == "postgres":
        raise ValueError("Administrative PostgreSQL containers cannot serve patient HTTP requests")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        if wired.close_request is not None and wired.patient_factory is None:
            await run_in_threadpool(wired.close_request)

    app = FastAPI(
        title="MediThread Agent API",
        version="0.1.0",
        description=(
            "Patient-facing API for the MediThread MVP. "
            "Persistence and agent routing are reported honestly per response; "
            "configured Gemini tools and Stage2 visual evidence preserve deterministic safety and user RLS."
        ),
        lifespan=lifespan,
    )
    app.state.container = wired
    # Public, non-sensitive release capabilities; read the same injected
    # configuration used by the patient factory, not a second dotenv load.
    app.state.medication_library_files_enabled = (
        effective_settings.enable_medication_library_files
        if effective_settings is not None and wired.persistence == "supabase"
        else wired.library_files is not None
    )
    app.state.care_task_followups_enabled = (
        effective_settings.enable_care_task_followups
        if effective_settings is not None and wired.persistence == "supabase"
        else True
    )
    app.state.late_dose_reports_enabled = (
        effective_settings.enable_late_dose_reports
        if effective_settings is not None and wired.persistence == "supabase"
        else wired.late_reports is not None
    )

    @app.middleware("http")
    async def request_resources(request, call_next):
        # Only the request owns its user-token HTTP pool. Never share it across
        # identities or retain it after a response/failure.
        try:
            return await call_next(request)
        finally:
            scoped = getattr(request.state, "patient_container", None)
            if scoped is not None and scoped.close_request is not None:
                await run_in_threadpool(scoped.close_request)

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
    app.include_router(long_term_routes.router)
    app.include_router(late_report_routes.router)

    LOGGER.info("PharmaScan Care transport created (persistence=%s)", wired.persistence)
    return app
