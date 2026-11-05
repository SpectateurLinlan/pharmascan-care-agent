"""One fixed patient-JWT readiness read; no clinical rows or implicit retries."""

import json
import math

import httpx
from pydantic import ValidationError

from ..contracts.workflow_runtime import RuntimeReleaseSnapshot
from ..domain.errors import DomainError, ProviderUnavailableError
from .supabase_data import SupabaseDataClient


class SupabaseRuntimeReadiness:
    def __init__(self, data: SupabaseDataClient):
        self._data = data

    def read_release(self, *, timeout_seconds: float) -> RuntimeReleaseSnapshot:
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 6:
            raise ProviderUnavailableError("Assistant readiness budget unavailable")
        try:
            raw = self._data.request(
                "POST",
                "/rest/v1/rpc/assistant_runtime_readiness",
                body={},
                timeout_seconds=timeout_seconds,
            )
            return RuntimeReleaseSnapshot.model_validate_json(json.dumps(raw))
        except (httpx.HTTPError, ValidationError, ValueError, TypeError, DomainError):
            raise ProviderUnavailableError("Assistant release readiness unavailable") from None
