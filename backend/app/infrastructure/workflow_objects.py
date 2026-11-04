"""Request-scoped owner-JWT immutable objects. Provisioning is deliberately external."""

import base64
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

import httpx

from ..config import validate_publishable_key
from ..contracts.workflow_attachments import DeleteReceipt, OriginalMime, StoredObject
from ..domain.errors import AuthenticationRequiredError, NotFoundError, ProviderUnavailableError, ValidationError

ObjectOperation = Literal["read", "put", "delete"]


@dataclass(frozen=True)
class WorkflowObjectAccess:
    # The composition root supplies an owned intent/control or cleanup-receipt check.
    permit: Callable[[UUID, UUID, UUID, ObjectOperation], bool]


class SupabaseWorkflowObjectAccess:
    """A fixed owned read of ticket/exclusion state, never a mutation fallback."""

    def __init__(self, data):
        self._data = data

    def permit(self, owner: UUID, task_id: UUID, attachment_id: UUID, operation: ObjectOperation) -> bool:
        self._data.check_patient(owner)
        if operation not in {"read", "put", "delete"}:
            raise ValidationError("Unsupported original operation")
        raw = self._data.request(
            "POST",
            "/rest/v1/rpc/assistant_original_object_access",
            body={
                "p_task": str(task_id),
                "p_attachment": str(attachment_id),
                "p_operation": operation,
            },
        )
        if not isinstance(raw, dict) or set(raw) != {"allowed"} or type(raw["allowed"]) is not bool:
            raise ProviderUnavailableError("Original access could not be checked")
        return raw["allowed"]


class LazyWorkflowObjects:
    """Defer token/storage construction until an actual object operation."""

    def __init__(self, factory: Callable[[], "SupabaseWorkflowObjects"]):
        self._factory = factory
        self._store = None

    def _get(self):
        if self._store is None:
            self._store = self._factory()
        return self._store

    def put_original(self, owner, task_id, upload_id, content, content_type, *, object_ref):
        return self._get().put_original(owner, task_id, upload_id, content, content_type, object_ref=object_ref)

    def read(self, owner, key):
        return self._get().read(owner, key)

    def delete(self, owner, key):
        return self._get().delete(owner, key)


class SupabaseWorkflowObjects:
    def __init__(
        self,
        *,
        owner: UUID,
        base_url: str,
        bucket: str,
        publishable_key: str,
        access_token: str,
        client: httpx.Client,
        access: WorkflowObjectAccess,
    ):
        validate_publishable_key(publishable_key)
        try:
            encoded = access_token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            if claims.get("role") != "authenticated" or UUID(claims.get("sub", "")) != owner:
                raise ValueError
        except (ValueError, TypeError, AttributeError, IndexError):
            raise AuthenticationRequiredError("Verified patient access token required") from None
        # This binding is defense in depth; transport auth verifies the JWT signature.
        url = urlparse(base_url)
        if url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost"}):
            raise ValidationError("Private storage needs an approved HTTPS or loopback endpoint")
        if not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}:
            raise ValidationError("Invalid private storage endpoint")
        if bucket != "medication-sources":
            raise ValidationError("An explicitly approved private medication-sources bucket is required")
        self._owner, self._client, self._access = owner, client, access
        self._base = base_url.rstrip("/") + f"/storage/v1/object/{bucket}/"
        self._headers = {"apikey": publishable_key, "Authorization": "Bearer " + access_token}

    def _key(self, owner: UUID, key: str, operation: ObjectOperation) -> tuple[UUID, UUID]:
        if owner != self._owner:
            raise AuthenticationRequiredError("Object context does not own this operation")
        parts = key.split("/")
        try:
            if len(parts) != 4 or parts[0] != str(owner) or parts[1] != "workflow-originals":
                raise ValueError
            task, attachment = UUID(parts[2]), UUID(parts[3])
            if str(task) != parts[2] or str(attachment) != parts[3] or re.search(r"[?%#\\]", key):
                raise ValueError
        except ValueError:
            raise ValidationError("Invalid private workflow object path") from None
        if not self._access.permit(owner, task, attachment, operation):
            raise ValidationError("Original access changed; check the current task or cleanup result")
        return task, attachment

    def _request(self, method: str, key: str, *, content: bytes | None = None, mime: OriginalMime = "image/png"):
        try:
            return self._client.request(
                method,
                self._base + key,
                content=content,
                headers={**self._headers, "Content-Type": mime, "x-upsert": "false", "Cache-Control": "no-store"},
                timeout=15,
            )
        except httpx.HTTPError:
            raise ProviderUnavailableError(
                "Original operation outcome is unknown; inspect its status before retrying"
            ) from None

    def put_original(
        self,
        owner: UUID,
        task_id: UUID,
        upload_id: UUID,
        content: bytes,
        content_type: OriginalMime,
        *,
        object_ref: str,
    ) -> StoredObject:
        task, _ = self._key(owner, object_ref, "put")
        limit = 10 * 1024 * 1024 if content_type == "application/pdf" else 8_000_000
        if (
            task != task_id
            or content_type not in {"image/png", "image/jpeg", "application/pdf"}
            or not 0 < len(content) <= limit
        ):
            raise ValidationError("Invalid original upload binding or content")
        response = self._request("POST", object_ref, content=content, mime=content_type)
        if response.status_code in {400, 409}:
            try:
                duplicate = response.json().get("error") in {"Duplicate", "ResourceAlreadyExists"}
            except (ValueError, AttributeError):
                duplicate = False
            if not duplicate:
                raise ProviderUnavailableError("Original upload was rejected")
        elif response.status_code >= 400:
            raise ProviderUnavailableError("Original upload was rejected")
        # An acknowledgement or duplicate alone does not prove which bytes exist.
        observed = self.read(owner, object_ref)
        digest = hashlib.sha256(content).hexdigest()
        if hashlib.sha256(observed).hexdigest() != digest:
            raise ProviderUnavailableError("Saved original bytes did not match; no overwrite was attempted")
        return StoredObject(object_ref=object_ref, checksum=digest, byte_size=len(observed))

    def read(self, owner: UUID, key: str) -> bytes:
        self._key(owner, key, "read")
        response = self._request("GET", key)
        if response.status_code == 404:
            raise NotFoundError("Original object not found")
        if response.status_code >= 400 or len(response.content) > 10 * 1024 * 1024:
            raise ProviderUnavailableError("Original object could not be read")
        return response.content

    def delete(self, owner: UUID, key: str) -> DeleteReceipt:
        self._key(owner, key, "delete")
        response = self._request("DELETE", key)
        if response.status_code >= 400 and response.status_code != 404:
            raise ProviderUnavailableError("Original cleanup outcome could not be confirmed")
        return DeleteReceipt(state="deleted")
