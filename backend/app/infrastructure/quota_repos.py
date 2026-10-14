"""User JWT calls only. No privileged database connection or editable counters."""

import secrets
from collections.abc import Callable
from uuid import UUID

from ..contracts.quota import Reservation, Usage
from .supabase_data import SupabaseDataClient


class SupabaseQuota:
    def __init__(self, client: SupabaseDataClient, *, nonce_factory: Callable[[], str] = lambda: secrets.token_hex(32)):
        self._client, self._nonce_factory = client, nonce_factory

    def usage(self, patient_id: UUID) -> Usage:
        self._client.check_patient(patient_id)
        return Usage.model_validate(self._client.request("POST", "/rest/v1/rpc/get_demo_ai_usage", body={}))

    def reserve(self, patient_id: UUID, turn_key: str) -> Reservation:
        self._client.check_patient(patient_id)
        nonce = self._nonce_factory()
        response = self._client.request(
            "POST", "/rest/v1/rpc/reserve_demo_ai_turn", body={"p_turn_key": turn_key, "p_nonce": nonce}
        )
        return Reservation(
            state=response["reservation"], usage=Usage.model_validate(response["usage"]), turn_key=turn_key, nonce=nonce
        )

    def model_request(self, patient_id: UUID, reservation: Reservation) -> None:
        self._client.check_patient(patient_id)
        self._client.request(
            "POST",
            "/rest/v1/rpc/record_demo_ai_request",
            body={
                "p_day": reservation.usage.usage_date.isoformat(),
                "p_turn_key": reservation.turn_key,
                "p_nonce": reservation.nonce,
            },
        )

    def finish(self, patient_id: UUID, reservation: Reservation, success: bool) -> Usage:
        self._client.check_patient(patient_id)
        return Usage.model_validate(
            self._client.request(
                "POST",
                "/rest/v1/rpc/finish_demo_ai_turn",
                body={
                    "p_day": reservation.usage.usage_date.isoformat(),
                    "p_turn_key": reservation.turn_key,
                    "p_nonce": reservation.nonce,
                    "p_success": success,
                },
            )
        )
