"""Request-scoped Supabase Data API transport. No administrative credentials."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from typing import Any
from uuid import UUID

import httpx

from ..config import validate_publishable_key
from ..domain.errors import AuthenticationRequiredError, ProviderUnavailableError, RegimenOverlapError, ValidationError


class SupabaseDataClient:
    def __init__(
        self,
        *,
        base_url: str,
        publishable_key: str,
        access_token: str,
        patient_id: UUID,
        client_factory: Callable[[], httpx.Client] = httpx.Client,
        client: httpx.Client | None = None,
    ) -> None:
        if not access_token or not publishable_key or publishable_key.startswith("sb_secret_"):
            raise AuthenticationRequiredError("User access token and publishable key required")
        self.patient_id = patient_id
        publishable_key = validate_publishable_key(publishable_key)
        self._base_url = base_url.rstrip("/")
        self._headers = {"apikey": publishable_key, "Authorization": f"Bearer {access_token}"}
        self._client_factory = client_factory
        self._client = client

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: object = None,
        prefer: str = "return=representation",
        include_total: bool = False,
    ) -> Any:
        # Requests are bounded; writes are not retried implicitly. The caller
        # can retry with its stable idempotency key after an uncertain outcome.
        try:
            with nullcontext(self._client) if self._client is not None else self._client_factory() as client:
                response = client.request(
                    method,
                    self._base_url + path,
                    params=params,
                    json=body,
                    headers={**self._headers, "Prefer": prefer},
                    timeout=15,
                )
        except httpx.HTTPError:
            raise ProviderUnavailableError("Supabase Data API unavailable") from None
        if response.status_code in (401, 403):
            raise AuthenticationRequiredError("Supabase rejected authenticated data access")
        if response.status_code >= 400:
            # Provider bodies may contain patient data. Never echo them.
            try:
                code = response.json().get("code", "unknown")
            except (ValueError, AttributeError):
                code = "malformed"
            if code == "P7504":
                from ..domain.errors import NotFoundError

                raise NotFoundError("Draft not found")
            if code == "P7502" or code == "23503":
                raise ValidationError("This draft has protected or shared records and cannot be deleted.")
            if code == "P7501":
                raise RegimenOverlapError()
            if response.status_code >= 500 or response.status_code == 429:
                raise ProviderUnavailableError(f"Supabase unavailable (HTTP {response.status_code})")
            safe_code = code if isinstance(code, str) and code.isalnum() and len(code) <= 12 else "unknown"
            raise ValidationError(f"Supabase rejected data operation (HTTP {response.status_code}; code {safe_code})")
        if not response.content:
            if include_total:
                raise ProviderUnavailableError("Complete records could not be verified. Please retry.")
            return None
        try:
            payload = response.json()
        except ValueError:
            raise ProviderUnavailableError("Supabase returned malformed JSON") from None
        if include_total:
            try:
                total = int(response.headers.get("content-range", "").rsplit("/", 1)[-1])
                if total < 0:
                    raise ValueError
            except ValueError:
                raise ProviderUnavailableError("Complete record counts could not be verified. Please retry.") from None
            return payload, total
        return payload

    def rows(self, table: str, **filters: str) -> list[dict[str, Any]]:
        if "and_" in filters:
            filters["and"] = filters.pop("and_")
        payload = self.request("GET", f"/rest/v1/{table}", params=filters)
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise ProviderUnavailableError("Supabase returned an invalid row collection")
        return payload

    def check_patient(self, patient_id: UUID) -> None:
        if patient_id != self.patient_id:
            raise AuthenticationRequiredError("Repository context does not own this operation")

    def all_rows(self, table: str, **filters: str) -> list[dict[str, Any]]:
        """Bounded complete collections, checked against PostgREST exact counts.

        Provider max-rows may be smaller than requested. Advance by actual
        returned rows; never silently use a truncated page as a full history.
        """
        if "and_" in filters:
            filters["and"] = filters.pop("and_")
        filters.setdefault("order", "id.asc")
        rows: list[dict[str, Any]] = []
        expected: int | None = None
        for _page in range(20):
            payload, total = self.request(
                "GET",
                f"/rest/v1/{table}",
                params={**filters, "limit": "200", "offset": str(len(rows))},
                prefer="count=exact",
                include_total=True,
            )
            if total > 2000:
                raise ProviderUnavailableError("The record window is too large; choose a shorter period.")
            if expected is not None and total != expected:
                raise ProviderUnavailableError("Records changed during loading. Please retry.")
            expected = total
            if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
                raise ProviderUnavailableError("Supabase returned an invalid row collection")
            rows.extend(payload)
            ids = [row["id"] for row in rows if "id" in row]
            if any(not isinstance(value, (str, int)) for value in ids):
                raise ProviderUnavailableError("Supabase returned an invalid row identifier")
            if len(ids) != len(set(ids)) or len(rows) > total:
                raise ProviderUnavailableError("Complete records could not be verified. Please retry.")
            if len(rows) == total:
                return rows
            if not payload:
                break
        raise ProviderUnavailableError("Complete records could not be verified. Please retry.")
