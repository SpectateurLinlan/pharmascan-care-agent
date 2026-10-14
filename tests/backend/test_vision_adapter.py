"""v0.8.0 adapter mapping/failure tests over SCHEMA_FIXTURE, never live inference."""

from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from app.contracts.vision import (
    EmbeddingResult,
    EmbeddingSpace,
    GalleryReference,
    ModelVersionMismatch,
    ScanBox,
    UnsupportedModality,
    VisionRequestError,
    VisionSchemaError,
    VisionUnavailable,
)
from app.infrastructure.stage2_adapter import FakeVisionProvider, HttpStage2VisionProvider, boxes_overlap
from app.infrastructure.stage2_http import HttpTransport, HttpxStage2Transport, sanitize_image
from app.infrastructure.stage2_label_adapter import PharmaScanLabelProvider
from app.infrastructure.stage2_schema import Stage2Contract
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/stage2/v0_8_0"
SPEC = json.loads((ROOT / "docs/external/pharmascan-api-openapi-0.8.0.json").read_text(encoding="utf-8"))
SPACE, MODEL, PREPROCESS = "SCHEMA-space-v0.8.0", "SCHEMA-model-v0.8.0", "SCHEMA-preprocess-v0.8.0"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class StubTransport(HttpTransport):
    def __init__(self, responses: dict | None = None, timeout: bool = False) -> None:
        super().__init__(base_url="https://example.invalid", timeout_seconds=1)
        self.responses, self.timeout, self.calls = responses or {}, timeout, []

    def _respond(self, path: str, body: object) -> dict:
        self.calls.append((path, body))
        if self.timeout:
            raise TimeoutError("SIMULATED")
        return self.responses[path]

    def get_json(self, path):
        return self._respond(path, None)

    def post_json(self, path, payload):
        return self._respond(path, payload)

    def post_multipart(self, path, files, data):
        return self._respond(path, (files, data))


def provider(responses=None, timeout=False):
    transport = StubTransport(responses, timeout)
    return HttpStage2VisionProvider(
        transport=transport,
        contract=Stage2Contract(SPEC),
        embedding_space_id=SPACE,
        model_version=MODEL,
        preprocessing_version=PREPROCESS,
    ), transport


def query(**changes) -> EmbeddingResult:
    data = fixture("embed_success")
    return EmbeddingResult(
        embedding=data["embedding"],
        dimension=256,
        embedding_space_id=SPACE,
        model_version=MODEL,
        preprocessing_version=PREPROCESS,
        normalized=True,
    ).model_copy(update=changes)


def gallery(**changes):
    return [
        GalleryReference(
            medication_id=f"med-{i}",
            name=f"Demo {i}",
            embeddings=[query().embedding],
            embedding_space_id=SPACE,
            model_version=MODEL,
            preprocessing_version=PREPROCESS,
        ).model_copy(update=changes)
        for i in (1, 2)
    ]


def test_embed_v08_maps_required_metadata_and_uses_image_not_file():
    p, t = provider({"/v1/embed": fixture("embed_success")})
    result = p.embed(image_bytes=b"stub-image", modality="loose_pill")
    assert result.dimension == 256 and result.preprocessing_version == PREPROCESS
    assert result.normalized and result.provider_request_id is None
    assert set(t.calls[0][1][0]) == {"image"}


@pytest.mark.parametrize("field", ["dim", "model_version", "embedding_space_id", "preprocess_version", "normalized"])
def test_missing_embed_metadata_fails_without_configuration_fallback(field):
    payload = fixture("embed_success")
    del payload[field]
    p, _ = provider({"/v1/embed": payload})
    with pytest.raises(VisionSchemaError):
        p.embed(image_bytes=b"stub", modality="loose_pill")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "0.1"])
def test_invalid_vector_numbers_fail(value):
    payload = fixture("embed_success")
    payload["embedding"][4] = value
    p, _ = provider({"/v1/embed": payload})
    with pytest.raises(VisionSchemaError):
        p.embed(image_bytes=b"stub", modality="loose_pill")


@pytest.mark.parametrize(
    "field,value",
    [
        ("embedding", [0.1] * 128),
        ("dim", 128),
        ("model_version", "other"),
        ("embedding_space_id", "other"),
        ("preprocess_version", "other"),
    ],
)
def test_embed_wrong_dimension_or_version_fails(field, value):
    payload = fixture("embed_success")
    payload[field] = value
    p, _ = provider({"/v1/embed": payload})
    with pytest.raises(ModelVersionMismatch):
        p.embed(image_bytes=b"stub", modality="loose_pill")


def test_normalization_claim_is_checked():
    payload = fixture("embed_success")
    payload["embedding"] = [0.5] * 256
    p, _ = provider({"/v1/embed": payload})
    with pytest.raises(VisionSchemaError):
        p.embed(image_bytes=b"stub", modality="loose_pill")


@pytest.mark.parametrize(
    "name,decision", [("match_success", "match"), ("match_unknown", "unknown"), ("match_ambiguous", "ambiguous")]
)
def test_match_maps_actual_similarity_threshold_margin_not_probability(name, decision):
    raw = fixture(name)
    p, t = provider({"/v1/match": raw})
    outcome = p.match(queries=[query()], gallery=gallery())
    assert outcome.decision == decision
    assert outcome.score == raw["results"][0]["similarity"]
    assert outcome.threshold == raw["threshold"] and outcome.margin == raw["margin"]
    assert outcome.closest.score == raw["results"][0]["closest"]["similarity"]
    assert outcome.threshold_version is None
    assert "confidence" not in outcome.model_dump() and "verified_identity" not in outcome.model_dump()
    assert t.calls[0][1]["embedding_space_id"] == SPACE
    assert outcome.medication_id == ("med-1" if decision == "match" else None)


@pytest.mark.parametrize("metadata", ["embedding_space_id", "model_version", "preprocessing_version"])
def test_gallery_and_query_version_guard_before_io(metadata):
    p, t = provider()
    with pytest.raises(ModelVersionMismatch):
        p.match(queries=[query(**{metadata: "different"})], gallery=gallery())
    with pytest.raises(ModelVersionMismatch):
        p.match(queries=[query()], gallery=gallery(**{metadata: "different"}))
    assert not t.calls


@pytest.mark.parametrize("bad", [[], [0.1] * 128, [float("nan")] * 256])
def test_match_invalid_query_vector_rejected(bad):
    p, t = provider()
    with pytest.raises((ModelVersionMismatch, VisionSchemaError)):
        p.match(queries=[query(embedding=bad)], gallery=gallery())
    assert not t.calls


def test_match_rejects_legacy_bare_vectors_multiple_queries_and_unknown_gallery_id():
    p, _ = provider({"/v1/match": fixture("match_success")})
    with pytest.raises(VisionSchemaError):
        p.match(queries=[[0.1] * 256], gallery=gallery())
    with pytest.raises(VisionSchemaError):
        p.match(queries=[query(), query()], gallery=gallery())
    raw = fixture("match_success")
    raw["results"][0]["closest"]["medication_id"] = "not-owned"
    p, _ = provider({"/v1/match": raw})
    with pytest.raises(VisionSchemaError):
        p.match(queries=[query()], gallery=gallery())


@pytest.mark.parametrize("field", ["results", "threshold", "margin", "model_version", "embedding_space_id", "evidence"])
def test_match_required_fields_not_invented(field):
    raw = fixture("match_success")
    del raw[field]
    p, _ = provider({"/v1/match": raw})
    with pytest.raises(VisionSchemaError):
        p.match(queries=[query()], gallery=gallery())


def test_v04_pills_response_is_rejected_not_silently_remapped():
    p, _ = provider({"/v1/match": {"pills": [{"decision": "match"}]}})
    with pytest.raises(VisionSchemaError):
        p.match(queries=[query()], gallery=gallery())


def test_detect_pixel_geometry_and_count_reliability_are_separate():
    raw = fixture("detect_success")
    p, _ = provider({"/v1/detect": raw})
    out = p.detect(image_bytes=b"stub")
    xyxy = raw["boxes"][0]
    assert out.boxes[0].x == xyxy[0] and out.boxes[0].w == xyxy[2] - xyxy[0]
    assert out.boxes[0].score is None
    assert out.provider_count_reliable == raw["count_reliable"]
    assert not out.usable_for_dose_count


def test_single_pill_two_overlapping_boxes_regression_stays_noncountable():
    raw = fixture("detect_unreliable_count")
    p, _ = provider({"/v1/detect": raw})
    out = p.detect(image_bytes=b"stub")
    assert out.duplicate_boxes and out.overlapping_boxes
    assert not out.provider_count_reliable and not out.usable_for_dose_count


@pytest.mark.parametrize("coords", [[1, 2, 3], [1, 2, 0, 4], [-1, 0, 4, 5], [0, 0, float("inf"), 1]])
def test_invalid_pixel_boxes_fail(coords):
    raw = fixture("detect_success")
    raw["boxes"][0] = coords
    p, _ = provider({"/v1/detect": raw})
    with pytest.raises(VisionSchemaError):
        p.detect(image_bytes=b"stub")


def test_scan_uses_nested_detection_never_unknown_scanpill_additions():
    raw = fixture("scan_success")
    raw["pills"][0]["decision"] = "clinically_safe"  # permitted extra JSON, NOT mapped.
    p, _ = provider({"/v1/scan": raw})
    out = p.scan_diagnostics(image_bytes=b"stub")
    assert out.pill_count == raw["detection"]["pill_count"]
    assert out.raw_decision is None and not out.usable_for_dose_count


def test_identify_uses_similarity_dose_form_and_candidates_only():
    raw = fixture("identify_success")
    p, _ = provider({"/v1/identify": raw})
    out = p.identify_candidates(image_bytes=b"stub")
    assert out[0].visual_similarity == raw["candidates"][0]["similarity"]
    assert out[0].form == raw["candidates"][0].get("dose_form")
    assert out[0].market == "US" and "confidence" not in out[0].model_dump()


@pytest.mark.parametrize("operation", ["embed", "match", "detect", "scan_diagnostics", "identify_candidates"])
def test_timeouts_never_return_success(operation):
    p, _ = provider(timeout=True)
    kwargs = {"queries": [query()], "gallery": gallery()} if operation == "match" else {"image_bytes": b"stub"}
    if operation == "embed":
        kwargs["modality"] = "loose_pill"
    with pytest.raises(VisionUnavailable):
        getattr(p, operation)(**kwargs)


def test_additional_fields_ignored_and_model_info_maps_opaque_calibration():
    raw = fixture("model_info_success")
    raw["unknown_future"] = {"instructions": "activate"}
    p, _ = provider({"/v1/model-info": raw})
    out = p.model_info()
    assert out.dimension == 256 and json.loads(out.calibration_json) == raw["calibration"]
    assert "unknown_future" not in out.model_dump()


@pytest.mark.parametrize("kind", ["package", "pharmacy_label", "prescription"])
def test_read_label_separates_identity_and_printed_instructions_never_activates(kind):
    raw = fixture("read_label_success")
    adapter = PharmaScanLabelProvider(transport=StubTransport({"/v1/read-label": raw}), contract=Stage2Contract(SPEC))
    out = adapter.extract_medication_source(source_document_id=UUID(int=1), source_kind=kind, image_bytes=b"stub")
    item = out.candidates[0]
    assert out.source_document_id == UUID(int=1) and out.review_required
    assert item.product.name == raw["candidates"][0]["name"]
    assert item.product.dose_form.line == raw["candidates"][0]["fields"]["dose_form"]["line"]
    for field in ("directions", "quantity", "date", "expiry_date"):
        actual = getattr(item.regimen_evidence, field)
        assert (actual.value, actual.line) == tuple(raw["candidates"][0]["fields"][field][x] for x in ("value", "line"))
    assert item.regimen_evidence.dose_amount is None and item.regimen_evidence.frequency is None
    assert item.regimen_evidence.administration_times is None and item.regimen_evidence.duration is None
    assert item.review_status == "extracted" and not item.can_activate_regimen


@pytest.mark.parametrize("omit", [False, True])
def test_read_label_missing_null_directions_distinguished_without_inference(omit):
    raw = fixture("read_label_missing_directions")
    if omit:
        raw["candidates"][0]["fields"].pop("directions", None)
    adapter = PharmaScanLabelProvider(transport=StubTransport({"/v1/read-label": raw}), contract=Stage2Contract(SPEC))
    item = adapter.extract_medication_source(
        source_document_id=UUID(int=1), source_kind="pharmacy_label", image_bytes=b"stub"
    ).candidates[0]
    assert item.regimen_evidence.directions is None
    assert "directions" in item.regimen_evidence.missing_fields
    assert ("directions" in item.regimen_evidence.explicit_null_fields) is not omit
    assert item.regimen_evidence.frequency is None and not item.can_activate_regimen


def test_empty_label_candidates_and_timeout_are_honest():
    raw = fixture("read_label_success")
    raw["candidates"] = []
    adapter = PharmaScanLabelProvider(transport=StubTransport({"/v1/read-label": raw}), contract=Stage2Contract(SPEC))
    assert (
        adapter.extract_medication_source(
            source_document_id=UUID(int=1), source_kind="package", image_bytes=b"stub"
        ).candidates
        == []
    )
    adapter = PharmaScanLabelProvider(transport=StubTransport(timeout=True), contract=Stage2Contract(SPEC))
    with pytest.raises(VisionUnavailable):
        adapter.extract_medication_source(source_document_id=UUID(int=1), source_kind="package", image_bytes=b"stub")


def png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(out, "PNG")
    return out.getvalue()


def real_transport(handler, retries=1, limit=2_000_000):
    sleeps = []
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpxStage2Transport(
        client=client,
        contract=Stage2Contract(SPEC),
        base_url="https://example.invalid",
        sleep=sleeps.append,
        get_retries=retries,
        max_response_bytes=limit,
    ), sleeps


@pytest.mark.parametrize(
    "body,ctype",
    [
        (b"<html>waking</html>", "text/html"),
        (b"{", "application/json"),
        (b"[]", "application/json"),
        (b"", "application/json"),
    ],
)
def test_transport_html_malformed_empty_nonobject_fail(body, ctype):
    t, _ = real_transport(lambda r: httpx.Response(200, content=body, headers={"Content-Type": ctype}))
    with pytest.raises(VisionSchemaError):
        t.get_json("/health")


def test_get_bounded_backoff_but_post_never_retried():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, json=fixture("common_error"))

    t, sleeps = real_transport(handler, retries=2)
    with pytest.raises(VisionUnavailable):
        t.get_json("/health")
    assert len(calls) == 3 and sleeps == [0.2, 0.4]
    calls.clear()
    with pytest.raises(VisionUnavailable):
        t.post_json("/v1/match", {})
    assert len(calls) == 1


def test_http_4xx_distinct_no_retry_and_size_limit():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(422, json=fixture("common_error"))

    t, _ = real_transport(handler)
    with pytest.raises(VisionRequestError) as exc:
        t.post_json("/v1/match", {})
    assert exc.value.status_code == 422 and len(calls) == 1
    t, _ = real_transport(lambda r: httpx.Response(200, json={"x": "a" * 100}), limit=10)
    with pytest.raises(VisionSchemaError):
        t.get_json("/health")


def test_multipart_actual_transport_validates_and_strips_image_metadata():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=fixture("embed_success"))

    t, _ = real_transport(handler)
    t.post_multipart("/v1/embed", {"image": png()}, {})
    assert b'name="image"' in requests[0].content and b"image/png" in requests[0].content
    with pytest.raises(VisionSchemaError):
        t.post_multipart("/v1/embed", {"image": b"not-an-image"}, {})
    assert len(requests) == 1
    assert sanitize_image(png()).startswith(b"\x89PNG")


def test_identify_real_multipart_uses_required_images_array_field():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=fixture("identify_success"))

    transport, _ = real_transport(handler)
    p = HttpStage2VisionProvider(
        transport=transport,
        contract=Stage2Contract(SPEC),
        embedding_space_id=SPACE,
        model_version=MODEL,
        preprocessing_version=PREPROCESS,
    )
    assert p.identify_candidates(image_bytes=png())
    schema = SPEC["components"]["schemas"]["Body_identify_v1_identify_post"]
    assert schema["required"] == ["images"]
    assert b'name="images"' in requests[0].content
    assert b'name="image"' not in requests[0].content
    with pytest.raises(VisionSchemaError):
        transport.post_multipart("/v1/identify", {"image": png()}, {})
    with pytest.raises(VisionSchemaError):
        transport.post_multipart("/v1/feedback", {"image": png()}, {})
    assert len(requests) == 1


def test_sanitize_image_removes_actual_exif_and_preserves_pixels():
    image = Image.new("RGB", (4, 4), (11, 22, 33))
    exif = Image.Exif()
    exif[270] = "SYNTHETIC EXIF MUST NOT LEAVE TRANSPORT"
    encoded = io.BytesIO()
    image.save(encoded, format="JPEG", exif=exif)
    with Image.open(io.BytesIO(encoded.getvalue())) as original:
        assert original.getexif()[270]
        original.load()
        pixels = original.convert("RGB").tobytes()
    cleaned = sanitize_image(encoded.getvalue())
    with Image.open(io.BytesIO(cleaned)) as result:
        assert result.format == "PNG" and not result.getexif()
        assert "exif" not in result.info
        assert result.convert("RGB").tobytes() == pixels


@pytest.mark.parametrize("limit", ["bytes", "pixels", "normalized_bytes"])
def test_sanitize_image_rejects_each_size_limit(limit):
    content = png()
    if limit == "bytes":
        options = {"max_bytes": len(content) - 1}
    elif limit == "pixels":
        options = {"max_pixels": 1}
    else:
        # A tiny JPEG is smaller than its normalized noisy RGB PNG. This
        # checks the output cap separately from the incoming byte cap.
        pixels = b"".join(hashlib.sha256(str(i).encode("ascii")).digest() for i in range(384))
        image = Image.frombytes("RGB", (64, 64), pixels)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=30)
        content = output.getvalue()
        assert len(sanitize_image(content)) > len(content)
        options = {"max_bytes": len(content)}
    with pytest.raises(VisionSchemaError):
        sanitize_image(content, **options)


def test_sanitize_image_decompression_warning_fails_closed(monkeypatch):
    # Lower Pillow's detector threshold locally; do not allocate a bomb image.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 2)
    with pytest.raises(VisionSchemaError):
        sanitize_image(png())


def test_structural_source_boundary_no_repository_or_activation_dependency():
    text = (ROOT / "backend/app/infrastructure/stage2_label_adapter.py").read_text(encoding="utf-8")
    assert "enrollment" not in text.split("class PharmaScanLabelProvider:")[1].replace("manual enrollment", "")
    assert "Repository" not in text and "activate_regimen(" not in text
    for file in (ROOT / "backend/app/application").glob("*.py"):
        assert "stage2_wire" not in file.read_text(encoding="utf-8")


def test_fake_and_embedding_guard_stay_explicit():
    fake = FakeVisionProvider()
    out = fake.match(queries=[fake.embed(image_bytes=b"x", modality="loose_pill")], gallery=[])
    assert fake.SIMULATED and "SIMULATED" in out.quality_flags and out.score is None
    assert fake.model_info().api_version == "SIMULATED"
    space = EmbeddingSpace(SPACE, MODEL, 256)
    with pytest.raises(ModelVersionMismatch):
        space.assert_compatible(space_id="wrong", model_version=MODEL, dimension=256)
    assert boxes_overlap([ScanBox(x=0, y=0, w=10, h=10), ScanBox(x=5, y=5, w=10, h=10)])
    assert not boxes_overlap([ScanBox(), ScanBox(x=5, y=5, w=10, h=10)])
    with pytest.raises(UnsupportedModality):
        fake.embed(image_bytes=b"x", modality="package")


def test_contract_is_immutable_against_caller_mutation():
    spec = copy.deepcopy(SPEC)
    contract = Stage2Contract(spec)
    spec["components"]["schemas"]["Embedding"]["required"] = []
    with pytest.raises(VisionSchemaError):
        contract.validate("Embedding", {})


def test_fixture_mutation_does_not_change_source_file():
    first = fixture("embed_success")
    mutated = copy.deepcopy(first)
    mutated["embedding"][0] = -1
    assert fixture("embed_success") == first
