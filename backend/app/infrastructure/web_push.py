"""RFC Web Push adapter. No provider body, endpoint or key is logged."""

import base64
import hashlib
import json
from collections.abc import Callable
from urllib.parse import urlsplit

import requests
from pywebpush import WebPushException, webpush

from ..contracts.notifications import Delivery, DeliveryResult


def validate_vapid_public(public: str | None) -> str:
    """Validate the browser application-server key without a private key."""
    from cryptography.hazmat.primitives.asymmetric import ec

    try:
        if not public:
            raise ValueError
        raw = base64.b64decode(public + "=" * (-len(public) % 4), altchars=b"-_", validate=True)
        if len(raw) != 65 or raw[0] != 4:
            raise ValueError
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except (ValueError, TypeError):
        raise ValueError("Invalid VAPID public key") from None
    return public


def validate_vapid(public: str | None, private: str | None, subject: str | None) -> None:
    """Fail closed on malformed/mismatched identity, without exposing key values."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    try:
        if not public or not private or not subject:
            raise ValueError
        raw = base64.b64decode(private + "=" * (-len(private) % 4), altchars=b"-_", validate=True)
        if len(raw) != 32:
            raise ValueError
        key = ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())
        expected = key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        actual = base64.b64decode(public + "=" * (-len(public) % 4), altchars=b"-_", validate=True)
        address = urlsplit(subject)
        if actual != expected or not (
            (address.scheme == "mailto" and "@" in address.path)
            or (address.scheme == "https" and address.hostname and not address.username and not address.password)
        ):
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("Invalid VAPID configuration") from None


class WebPushProvider:
    def __init__(
        self, *, private_key: str, subject: str, send: Callable = webpush, session_factory: Callable | None = None
    ):
        self._key, self._subject, self._send = private_key, subject, send
        self._session_factory = session_factory or NoRedirectSession

    def send(self, delivery: Delivery) -> DeliveryResult:
        try:
            with self._session_factory() as session:
                response = self._send(
                    subscription_info=delivery.subscription.model_dump(),
                    data=json.dumps(
                        {
                            "title": "PharmaScan Care",
                            "body": "This is a test notification."
                            if delivery.purpose == "test"
                            else "It's time to check your medication plan.",
                            "purpose": delivery.purpose,
                            "language": delivery.language,
                            "url": "/#today",
                            "tag": hashlib.sha256(str(delivery.id).encode()).hexdigest()[:32],
                        }
                    ),
                    vapid_private_key=self._key,
                    vapid_claims={"sub": self._subject},
                    ttl=300,
                    timeout=10,
                    requests_session=session,
                )
                if not isinstance(response, requests.Response) or not 200 <= response.status_code < 300:
                    return DeliveryResult(status="provider_rejected")
        except WebPushException as error:
            response = error.response
            code = response.status_code if response is not None else None
            if code in (404, 410):
                return DeliveryResult(status="expired_subscription")
            if code in (429, 503):
                retry = response.headers.get("Retry-After", "60")
                # Missing/unparseable dates are conservatively delayed five minutes.
                delay = max(60, min(int(retry), 86400)) if retry.isdigit() else 300
                return DeliveryResult(status="temporary", retry_seconds=delay)
            return DeliveryResult(status="provider_rejected")
        except requests.RequestException:
            # Timeout may follow acceptance. Do not replay an uncertain send.
            return DeliveryResult(status="uncertain_delivery")
        except (ValueError, TypeError):
            return DeliveryResult(status="invalid_subscription")
        return DeliveryResult(status="sent")


class NoRedirectSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs["allow_redirects"] = False
        return super().request(method, url, **kwargs)
