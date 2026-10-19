"""Separate worker ASGI factory. Never mounted in the patient application."""

import hashlib
import hmac
import logging
import secrets
import time
from collections.abc import Callable
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..config import Settings
from ..contracts.notifications import DispatchRunner
from ..infrastructure.dispatch_process import DispatchTimeout, DispatchUnavailable, ProcessDispatchRunner


def create_dispatcher_app(
    *,
    runner: DispatchRunner | None = None,
    synthetic_runner: DispatchRunner | None = None,
    token: str | None = None,
    settings: Settings | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    wall_time: Callable[[], float] = time.time,
    request_ids: Callable[[], UUID] = uuid4,
) -> FastAPI:
    """Fixed operation only: no patient id, destination, shell command or payload."""
    effective = settings or (Settings.from_env() if token is None else None)
    credential = token if token is not None else effective.push_dispatch_token
    if not credential or len(credential) < 32 or not credential.isascii():
        raise ValueError("PUSH_DISPATCH_TOKEN must be a dedicated ASCII secret of at least 32 characters")
    worker = runner or ProcessDispatchRunner()
    scoped_worker = synthetic_runner or (
        ProcessDispatchRunner(synthetic_only=True) if effective and effective.push_synthetic_patient_id else None
    )
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.router.redirect_slashes = False
    logger = logging.getLogger("pharmascan.dispatch")

    @app.get("/health", include_in_schema=False)
    async def health():
        """Unauthenticated liveness only; it does not contact DB or push provider."""
        return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})

    @app.post("/internal/notifications/dispatch")
    @app.post("/internal/notifications/dispatch-synthetic")
    async def dispatch(request: Request):
        correlation = request_ids().hex
        started = monotonic()

        def reply(status: int, body: dict) -> JSONResponse:
            # No credentials, owner ids, endpoints, provider bodies or exception text.
            logger.info(
                "dispatch correlation=%s status=%s duration_ms=%d",
                correlation,
                status,
                int((monotonic() - started) * 1000),
            )
            return JSONResponse(
                body, status_code=status, headers={"Cache-Control": "no-store", "X-Request-ID": correlation}
            )

        stamp = request.headers.get("x-dispatch-timestamp", "")
        synthetic = request.url.path == "/internal/notifications/dispatch-synthetic"
        message = f"POST\n{request.url.path}\n{stamp}".encode()
        signature = hmac.new(credential.encode(), message, hashlib.sha256).hexdigest()
        supplied = request.headers.get("x-dispatch-signature", "")
        if (
            not stamp.isascii()
            or not stamp.isdigit()
            or len(stamp) > 11
            or abs(wall_time() - int(stamp)) > 60
            or not secrets.compare_digest(supplied.encode(), signature.encode())
        ):
            return reply(401, {"error": {"code": "AUTH_REQUIRED"}})
        if request.headers.get("origin") or request.query_params or request.headers.get("transfer-encoding"):
            return reply(400, {"error": {"code": "INVALID_INPUT"}})
        if request.headers.get("content-length", "0") not in ("0", "2") or await request.body() not in (b"", b"{}"):
            return reply(400, {"error": {"code": "EMPTY_BODY_REQUIRED"}})
        selected_worker = scoped_worker if synthetic else worker
        if selected_worker is None:
            return reply(404, {"error": {"code": "NOT_ENABLED"}})
        try:
            result = await run_in_threadpool(selected_worker.run)
        except DispatchTimeout:
            return reply(504, {"error": {"code": "DISPATCH_TIMEOUT"}})
        except DispatchUnavailable:
            return reply(503, {"error": {"code": "DISPATCH_UNAVAILABLE"}})
        logger.info(
            "dispatch_result correlation=%s outcome=%s processed=%d profiles=%d synthetic=%s",
            correlation,
            result.status,
            result.processed,
            result.profiles,
            synthetic,
        )
        return reply(200, result.model_dump())

    return app
