"""Authenticated patient context.

Boundary implemented here:

    React -> Supabase Auth -> user JWT -> FastAPI
          -> authenticated user context -> Repository -> patient-owned records

Two rules are non-negotiable (AGENTS.md rule 22, docs/ARCHITECTURE.md):

* the patient id used for every repository call is derived from a **verified**
  identity, never from the request body, a query parameter or anything the LLM
  produced;
* no privileged/service-role credential is ever handed to the browser.

Modes
-----
``supabase``
    A ``Authorization: Bearer <access token>`` header is required. The token is
    verified against the project's Auth API; only then is ``sub`` accepted as
    the patient id. A missing, malformed or rejected token raises
    ``AUTH_REQUIRED`` and no repository call happens.
``demo``
    The anonymous, per-evaluator demo principal: a synthetic patient id is
    derived from a browser ``client_id``. This is explicitly **NOT**
    authentication, is only reachable when the deployment opts into it, and is
    reported as unauthenticated in the principal.

Verification is delegated to an injected ``TokenVerifier`` so the transport
never contains provider specifics and a test can inject a deterministic
verifier without weakening the production path.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from ..domain.errors import AuthenticationRequiredError

#: Header the browser sends; never logged, never echoed.
AUTHORIZATION_HEADER = "authorization"
BEARER_PREFIX = "bearer "


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """The verified identity every repository call is scoped to."""

    patient_id: UUID
    subject: str
    email: str | None
    authenticated: bool
    mode: str

    def describe(self) -> dict[str, Any]:
        """Diagnostic view safe to log (no token, no raw claims)."""
        return {
            "patient_id": str(self.patient_id),
            "subject": self.subject,
            "authenticated": self.authenticated,
            "mode": self.mode,
        }


class TokenVerifier(Protocol):
    """Verifies an access token and returns its claims."""

    name: str

    def verify(self, token: str) -> Mapping[str, Any]: ...


class SupabaseAuthApiVerifier:
    """Verify a Supabase access token against the project's Auth API.

    The publishable (anon) key is sent as ``apikey``; the user's access token is
    sent as the bearer credential. A non-200 response, a malformed body or a
    missing/invalid ``id`` is a hard failure — an unverified token never yields
    a principal.
    """

    name = "supabase_auth_api"

    def __init__(self, *, supabase_url: str, api_key: str, timeout_s: float = 5.0) -> None:
        if not supabase_url or not api_key:
            raise ValueError("supabase_url and api_key are required")
        self._base = supabase_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_s

    def verify(self, token: str) -> Mapping[str, Any]:
        if not token:
            raise AuthenticationRequiredError("No access token was presented")
        request = urllib.request.Request(  # noqa: S310 - fixed https endpoint
            f"{self._base}/auth/v1/user",
            headers={"apikey": self._api_key, "Authorization": f"Bearer {token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # 401/403 => the token is not valid. Never include the token.
            raise AuthenticationRequiredError(
                f"Access token rejected by the identity provider (HTTP {exc.code})"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AuthenticationRequiredError(
                "Could not verify the access token with the identity provider"
            ) from exc

        if not isinstance(payload, dict) or not payload.get("id"):
            raise AuthenticationRequiredError("Identity provider returned no subject")
        return {"sub": str(payload["id"]), "email": payload.get("email")}


class StaticTokenVerifier:
    """Deterministic verifier for tests. Never selected by the composition root
    unless it is handed in explicitly, and never used to claim real auth."""

    name = "static_test_verifier"

    def __init__(self, tokens: Mapping[str, Mapping[str, Any]]) -> None:
        self._tokens = dict(tokens)

    def verify(self, token: str) -> Mapping[str, Any]:
        claims = self._tokens.get(token)
        if claims is None:
            raise AuthenticationRequiredError("Access token rejected")
        return claims


class AuthBoundary:
    """Resolves an inbound request to exactly one verified principal."""

    def __init__(
        self,
        *,
        mode: str,
        verifier: TokenVerifier | None = None,
        demo_patient_id=None,
    ) -> None:
        if mode not in ("supabase", "demo"):
            raise ValueError(f"unsupported auth mode {mode!r}")
        if mode == "supabase" and verifier is None:
            raise ValueError("supabase auth mode requires a token verifier")
        self._mode = mode
        self._verifier = verifier
        self._demo_patient_id = demo_patient_id

    @property
    def mode(self) -> str:
        return self._mode

    def resolve(
        self, *, authorization: str | None, client_id: str | None
    ) -> AuthenticatedPrincipal:
        """Return the principal for this request, or raise ``AUTH_REQUIRED``."""
        if self._mode == "supabase":
            return self._resolve_supabase(authorization)
        return self._resolve_demo(client_id)

    # -- modes ---------------------------------------------------------------

    def _resolve_supabase(self, authorization: str | None) -> AuthenticatedPrincipal:
        token = _bearer_token(authorization)
        if token is None:
            raise AuthenticationRequiredError(
                "A bearer access token is required for this endpoint"
            )
        assert self._verifier is not None  # guaranteed by __init__
        claims = self._verifier.verify(token)
        subject = claims.get("sub")
        if not subject:
            raise AuthenticationRequiredError("Verified token carried no subject")
        try:
            patient_id = UUID(str(subject))
        except ValueError as exc:
            raise AuthenticationRequiredError(
                "Verified token subject is not a valid patient identifier"
            ) from exc
        email = claims.get("email")
        return AuthenticatedPrincipal(
            patient_id=patient_id,
            subject=str(subject),
            email=str(email) if email else None,
            authenticated=True,
            mode=self._mode,
        )

    def _resolve_demo(self, client_id: str | None) -> AuthenticatedPrincipal:
        """Anonymous demo principal. NOT authentication.

        ``patient_id`` is derived from the browser ``client_id`` so two
        evaluators never share a record; nothing here verifies a human.
        """
        if not client_id or not client_id.strip():
            raise AuthenticationRequiredError("client_id is required in demo mode")
        if self._demo_patient_id is None:  # pragma: no cover - wiring error
            raise AuthenticationRequiredError("demo principal derivation is not configured")
        return AuthenticatedPrincipal(
            patient_id=self._demo_patient_id(client_id),
            subject=f"demo:{client_id}",
            email=None,
            authenticated=False,
            mode=self._mode,
        )


def _bearer_token(authorization: str | None) -> str | None:
    """Extract the bearer token, or ``None`` when the header is absent/invalid."""
    if not authorization:
        return None
    value = authorization.strip()
    if not value.lower().startswith(BEARER_PREFIX):
        return None
    token = value[len(BEARER_PREFIX) :].strip()
    return token or None
