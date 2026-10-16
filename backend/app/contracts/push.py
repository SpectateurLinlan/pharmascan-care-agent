"""Typed patient subscription boundary. Endpoints are restricted to push providers."""

import base64
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PushKeys(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p256dh: str = Field(max_length=100)
    auth: str = Field(max_length=30)

    @field_validator("p256dh", "auth")
    @classmethod
    def valid_key(cls, value, info):
        try:
            raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        except ValueError:
            raise ValueError("Invalid subscription key") from None
        if (info.field_name == "auth" and len(raw) != 16) or (
            info.field_name == "p256dh" and (len(raw) != 65 or raw[0] != 4)
        ):
            raise ValueError("Invalid subscription key")
        return value


class PushSubscriptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(max_length=2048)
    keys: PushKeys

    @field_validator("endpoint")
    @classmethod
    def valid_endpoint(cls, value: str) -> str:
        try:
            url = urlsplit(value)
            host = url.hostname or ""
            allowed = (
                host in {"fcm.googleapis.com", "updates.push.services.mozilla.com"}
                or host.endswith(".push.apple.com")
                or host == "web.push.apple.com"
                or host.endswith(".notify.windows.com")
            )
            if (
                url.scheme != "https"
                or not allowed
                or url.port not in (None, 443)
                or url.username
                or url.password
                or url.fragment
            ):
                raise ValueError
        except ValueError:
            raise ValueError("Unsupported push service endpoint") from None
        return value


class PushSubscriptionRecord(BaseModel):
    id: UUID
    enabled: bool


class PushConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    available: bool
    public_key: str | None
    test_available: bool = False


class PushSubscriptions(Protocol):
    def save(self, patient_id: UUID, subscription: PushSubscriptionInput) -> PushSubscriptionRecord: ...
    def revoke_endpoint(self, patient_id: UUID, endpoint: str) -> None: ...
    def revoke(self, patient_id: UUID, subscription_id: UUID) -> None: ...
    def list_for_patient(self, patient_id: UUID) -> list[PushSubscriptionRecord]: ...
    def current(self, patient_id: UUID, endpoint: str) -> PushSubscriptionRecord | None: ...
    def credentials(self, patient_id: UUID, subscription_id: UUID) -> PushSubscriptionInput | None: ...
