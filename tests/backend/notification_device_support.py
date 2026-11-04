"""DEMO_ONLY owned memory subscription port; never contacts a push service."""

from uuid import uuid4

from app.contracts.push import PushSubscriptionRecord
from app.domain.errors import NotFoundError


class SyntheticSubscriptions:
    def __init__(self):
        self.rows = {}
        self.writes = 0

    def save(self, owner, value):
        key = owner, value.endpoint
        previous = self.rows.get(key)
        row = PushSubscriptionRecord(id=previous[1].id if previous else uuid4(), enabled=True)
        self.rows[key] = value, row
        self.writes += 1
        return row

    def current(self, owner, endpoint):
        value = self.rows.get((owner, endpoint))
        return value[1] if value else None

    def revoke_endpoint(self, owner, endpoint):
        previous = self.rows.get((owner, endpoint))
        if previous:
            self.rows[owner, endpoint] = previous[0], previous[1].model_copy(update={"enabled": False})
            self.writes += 1

    def revoke(self, owner, subscription_id):
        for (patient, endpoint), (_, row) in self.rows.items():
            if patient == owner and row.id == subscription_id:
                self.revoke_endpoint(owner, endpoint)
                return
        raise NotFoundError("Owned synthetic subscription not found")

    def list_for_patient(self, owner):
        return [row for (patient, _), (_, row) in self.rows.items() if patient == owner]

    def credentials(self, owner, subscription_id):
        return next((value for (patient, _), (value, row) in self.rows.items()
                     if patient == owner and row.id == subscription_id and row.enabled), None)
