"""Same-user JWT only. Subscription secrets never appear in public responses."""

from uuid import UUID

from ..contracts.push import PushSubscriptionInput, PushSubscriptionRecord
from .supabase_data import SupabaseDataClient


class SupabasePushSubscriptions:
    def __init__(self, client: SupabaseDataClient):
        self._client = client

    def save(self, patient_id: UUID, subscription: PushSubscriptionInput) -> PushSubscriptionRecord:
        self._client.check_patient(patient_id)
        rows = self._client.request(
            "POST",
            "/rest/v1/push_subscriptions",
            params={"on_conflict": "patient_id,endpoint"},
            body={"patient_id": str(patient_id), **subscription.model_dump(), "enabled": True},
            prefer="resolution=merge-duplicates,return=representation",
        )
        return PushSubscriptionRecord(id=rows[0]["id"], enabled=rows[0]["enabled"])

    def revoke_endpoint(self, patient_id: UUID, endpoint: str) -> None:
        self._client.check_patient(patient_id)
        self._client.request(
            "PATCH",
            "/rest/v1/push_subscriptions",
            params={"patient_id": f"eq.{patient_id}", "endpoint": f"eq.{endpoint}"},
            body={"enabled": False},
        )

    def revoke(self, patient_id: UUID, subscription_id: UUID) -> None:
        self._client.check_patient(patient_id)
        self._client.request(
            "PATCH",
            "/rest/v1/push_subscriptions",
            params={"patient_id": f"eq.{patient_id}", "id": f"eq.{subscription_id}"},
            body={"enabled": False},
        )

    def list_for_patient(self, patient_id: UUID) -> list[PushSubscriptionRecord]:
        self._client.check_patient(patient_id)
        return [
            PushSubscriptionRecord.model_validate(row)
            for row in self._client.rows("push_subscriptions", patient_id=f"eq.{patient_id}", select="id,enabled")
        ]

    def current(self, patient_id: UUID, endpoint: str) -> PushSubscriptionRecord | None:
        self._client.check_patient(patient_id)
        rows = self._client.rows(
            "push_subscriptions", patient_id=f"eq.{patient_id}", endpoint=f"eq.{endpoint}", select="id,enabled"
        )
        return PushSubscriptionRecord.model_validate(rows[0]) if rows else None

    def credentials(self, patient_id: UUID, subscription_id: UUID) -> PushSubscriptionInput | None:
        self._client.check_patient(patient_id)
        rows = self._client.rows(
            "push_subscriptions",
            patient_id=f"eq.{patient_id}",
            id=f"eq.{subscription_id}",
            enabled="eq.true",
            select="endpoint,keys",
        )
        return PushSubscriptionInput.model_validate(rows[0]) if rows else None
