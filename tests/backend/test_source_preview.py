"""VERIFIED LOCAL source-preview application path, SCHEMA FIXTURE provider."""

import io
import json
from pathlib import Path

import httpx
import pytest
from app.application.source_preview import SourcePreviewService
from app.domain.errors import ValidationError
from app.infrastructure.source_gateway import SourceGateway
from app.infrastructure.stage2_schema import Stage2Contract
from app.transport.app_factory import create_app
from app.transport.container import build_container
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def synthetic_png():
    output = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(output, format="PNG")
    return output.getvalue()


def test_source_preview_preserves_evidence_without_any_regimen_or_dose_write():
    fixture = json.loads((ROOT / "tests/fixtures/stage2/v0_8_0/read_label_success.json").read_text(encoding="utf-8"))
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == "/v1/read-label"
        return httpx.Response(200, json=fixture)

    container = build_container()
    contract = Stage2Contract(
        json.loads((ROOT / "docs/external/pharmascan-api-openapi-0.8.0.json").read_text(encoding="utf-8"))
    )
    provider = SourceGateway(
        base_url="https://example.invalid",
        contract=contract,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    container.source_preview = SourcePreviewService(provider=provider, ids=container.ids)
    client = TestClient(create_app(container))
    path = "/api/sources/preview?client_id=DEMO&source_kind=pharmacy_label"
    headers = {"Content-Type": "image/png", "X-Stage2-Consent": "true", "X-Demo-Only": "true"}
    no_auth = client.post("/api/sources/preview?source_kind=pharmacy_label", headers=headers, content=synthetic_png())
    assert no_auth.status_code == 401
    refusal = client.post(path, headers={"Content-Type": "image/png"}, content=synthetic_png())
    assert refusal.status_code == 422 and not calls
    result = client.post(path, headers=headers, content=synthetic_png())
    assert result.status_code == 200
    payload = result.json()
    assert payload["review_required"] and payload["source_document_id"]
    assert payload["candidates"][0]["product"]["source_lines"]
    for candidate in payload["candidates"]:
        assert candidate["can_activate_regimen"] is False and candidate["review_status"] == "extracted"
        assert candidate["regimen_evidence"]["dose_amount"] is None
        assert candidate["regimen_evidence"]["administration_times"] is None
    assert not container.store.regimens and not container.store.events and not container.store.sources
    mismatch = client.post(path, headers={**headers, "Content-Type": "image/jpeg"}, content=synthetic_png())
    assert mismatch.status_code == 422 and len(calls) == 1
    rejected_pdf = client.post(path, headers={**headers, "Content-Type": "application/pdf"}, content=b"%PDF")
    assert rejected_pdf.status_code == 422


def test_malformed_image_never_reaches_stage2():
    contract = Stage2Contract(
        json.loads((ROOT / "docs/external/pharmascan-api-openapi-0.8.0.json").read_text(encoding="utf-8"))
    )
    provider = SourceGateway(
        base_url="https://example.invalid",
        contract=contract,
        client_factory=lambda: pytest.fail("Do not send malformed image"),
    )
    with pytest.raises(ValidationError):
        provider.extract_medication_source(
            source_document_id=build_container().ids.new_id(), source_kind="pharmacy_label", image_bytes=b"html"
        )
