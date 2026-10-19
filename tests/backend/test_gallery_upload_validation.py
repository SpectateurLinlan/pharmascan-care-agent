"""Request-level upload signature checks; all bytes are synthetic test fixtures."""

import asyncio

import pytest
from app.domain.errors import ValidationError
from app.transport.routes.evidence import image_content
from starlette.requests import Request


def request_for(content_type: str, body: bytes) -> Request:
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/evidence/gallery/DEMO-med/images",
            "query_string": b"",
            "headers": [(b"content-type", content_type.encode())],
        },
        receive,
    )


@pytest.mark.parametrize(
    ("content_type", "body"),
    [
        ("application/pdf", b"%PDF-1.7 DEMO_ONLY"),
        ("image/png", b"DEMO bytes without a PNG signature"),
        ("image/jpeg", b"\x89PNG\r\n\x1a\nDEMO mismatched signature"),
    ],
)
def test_gallery_upload_rejects_unsupported_or_mismatched_image_types(content_type: str, body: bytes):
    with pytest.raises(ValidationError):
        asyncio.run(image_content(request_for(content_type, body)))
