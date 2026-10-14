"""AUTOMATED fixture Stage2 I/O, real HTTP/application safety boundaries."""

import io
import json
from pathlib import Path

import httpx
import pytest
from app.application.visual_check import VisualCheckService
from app.infrastructure.stage2_schema import Stage2Contract
from app.infrastructure.visual_gateway import VisualGateway
from app.transport.app_factory import create_app
from app.transport.container import build_container
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "version,dimension,opt_in", [("0.9.0", 256, False), ("0.10.0", 256, True), ("0.9.0", 512, True)]
)
def test_minor_read_only_compatibility_never_disables_version_or_dimension_guard(version, dimension, opt_in):
    from app.contracts.vision import ModelVersionMismatch
    from app.infrastructure.stage2_adapter import HttpStage2VisionProvider

    fixture = json.loads((ROOT / "tests/fixtures/stage2/v0_8_0/model_info_success.json").read_text(encoding="utf-8"))
    fixture.update(api_version=version, embedding_dim=dimension)

    class Transport:
        def get_json(self, path):
            return fixture

    contract = Stage2Contract(
        json.loads((ROOT / "docs/external/pharmascan-api-openapi-0.8.0.json").read_text(encoding="utf-8"))
    )
    provider = HttpStage2VisionProvider(
        transport=Transport(),
        contract=contract,
        embedding_space_id=fixture["embedding_space_id"],
        model_version=fixture["model_version"],
        preprocessing_version=fixture["preprocess_version"],
    )
    with pytest.raises(ModelVersionMismatch):
        provider.model_info(read_only_v09_compatibility=opt_in)


@pytest.mark.parametrize("overlap", [False, True])
@pytest.mark.parametrize("api_version", ["0.8.0", "0.9.0"])
def test_visual_http_uses_strict_stage2_candidate_evidence_no_clinical_writes(overlap, api_version):
    folder = ROOT / "tests/fixtures/stage2/v0_8_0"
    calls = []

    def handler(request):
        calls.append(request.url.path)
        file = {
            "/v1/model-info": "model_info_success.json",
            "/v1/detect": "detect_success.json",
            "/v1/identify": "identify_success.json",
        }[request.url.path]
        fixture = json.loads((folder / file).read_text(encoding="utf-8"))
        if request.url.path == "/v1/model-info":
            fixture["api_version"] = api_version
        if overlap and request.url.path == "/v1/detect":
            fixture["pill_count"] = 2
            fixture["boxes"] = [fixture["boxes"][0], fixture["boxes"][0]]
            fixture["box_flags"] = [[], []]
        return httpx.Response(200, json=fixture)

    contract = Stage2Contract(
        json.loads((ROOT / "docs/external/pharmascan-api-openapi-0.8.0.json").read_text(encoding="utf-8"))
    )
    container = build_container()
    container.visual_check = VisualCheckService(
        provider=VisualGateway(
            base_url="https://example.invalid",
            contract=contract,
            client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
        )
    )
    client = TestClient(create_app(container))
    image = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(image, format="PNG")
    headers = {"Content-Type": "image/png", "X-Stage2-Consent": "true", "X-Demo-Only": "true"}
    assert client.post("/api/visual-check", headers=headers, content=image.getvalue()).status_code == 401
    response = client.post("/api/visual-check?client_id=DEMO", headers=headers, content=image.getvalue())
    assert response.status_code == 200
    result = response.json()
    assert result["decision"] == ("ambiguous" if overlap else "unknown")
    assert result["candidates"] and not result["comparison_available"]
    assert not result["safe_to_take_confirmed"] and not result["ingestion_proven"]
    assert calls.count("/v1/detect") == 1 and calls.count("/v1/identify") == 1
    assert not container.store.events and not container.store.regimens
    response = client.post(
        "/api/visual-check?client_id=DEMO", headers={**headers, "Content-Type": "image/jpeg"}, content=image.getvalue()
    )
    assert response.status_code == 422 and calls.count("/v1/detect") == 1


def test_visual_foreign_regimen_fails_before_provider(wired):
    from uuid import UUID

    from app.domain.errors import NotFoundError

    class Refused:
        def inspect(self, image):
            pytest.fail("Foreign regimen must not reach provider")

    with pytest.raises(NotFoundError):
        VisualCheckService(provider=Refused()).check(
            patient_id=UUID(int=100),
            regimen_id=UUID(int=999),
            image=b"synthetic",
            consent=True,
            demo_only=True,
            enrollment=wired.enrollment,
        )
