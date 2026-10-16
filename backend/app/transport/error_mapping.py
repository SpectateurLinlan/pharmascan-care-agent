"""Domain error -> HTTP status mapping.

Kept in one table so every route maps errors identically and the client can
branch on the stable ``code`` rather than parsing prose. The mapping never
converts a policy block into a 200.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from ..domain.errors import (
    AuthenticationRequiredError,
    ConfirmationExpiredError,
    ConfirmationRequiredError,
    DomainError,
    DuplicateEventError,
    IncompleteRegimenError,
    NotFoundError,
    PolicyBlockedError,
    ProviderUnavailableError,
    RegimenOverlapError,
    SourceUnreviewedError,
    StaleVersionError,
    ValidationError,
)

#: Domain exception class -> (http status, stable code fallback)
_STATUS_BY_ERROR: dict[type[DomainError], int] = {
    AuthenticationRequiredError: 401,
    NotFoundError: 404,
    SourceUnreviewedError: 409,
    IncompleteRegimenError: 409,
    StaleVersionError: 409,
    ConfirmationRequiredError: 409,
    ConfirmationExpiredError: 410,
    DuplicateEventError: 409,
    RegimenOverlapError: 409,
    PolicyBlockedError: 422,
    ProviderUnavailableError: 503,
    ValidationError: 422,
}


def status_for(exc: DomainError) -> int:
    for error_type, status in _STATUS_BY_ERROR.items():
        if isinstance(exc, error_type):
            return status
    return 400


def error_payload(exc: DomainError) -> dict[str, object]:
    return {
        "code": exc.code.value,
        "message": str(exc),
        "rule_id": exc.rule_id.value if exc.rule_id else None,
    }


async def domain_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return JSONResponse(status_code=status_for(exc), content=error_payload(exc))
