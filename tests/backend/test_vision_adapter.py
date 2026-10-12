"""Vision adapter tests (Gate 2).

These prove the *adapter* contract: strict mapping, explicit failure states
and the known single-pill double-box regression. They use a stubbed
transport, so they do NOT prove anything about the live Stage2 deploy (B01).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.infrastructure.stage2_adapter import (
    FakeVisionProvider,
    HttpStage2VisionProvider,
    HttpTransport,
    _has_overlap,
)
from app.infrastructure.vision_contracts import (
    EmbeddingSpace,
    GalleryReference,
    ModelVersionMismatch,
    PillCandidate,
    ScanBox,
    UnsupportedModality,
    VisionSchemaError,
    VisionUnavailable,
)

SPACE = "stage2-c3pi-v1"
MODEL = "encoder-2026-08"


class StubTransport(HttpTransport):
    """Injected stub; records calls and replays scripted responses."""

    def __init__(self, *, responses: dict[str, Any] | None = None, raise_timeout: bool = False) -> None:
        super().__init__(base_url="https://example.invalid", timeout_seconds=5.0)
        self._responses = responses or {}
        self._raise_timeout = raise_timeout
        self.calls: list[tuple[str, Any]] = []

    def _respond(self, path: str, payload: Any) -> dict[str, Any]:
        self.calls.append((path, payload))
        if self._raise_timeout:
            raise TimeoutError("simulated transport timeout")
        response = self._responses.get(path)
        if response is None:
            raise AssertionError(f"stub has no response for {path}")
        if isinstance(response, Exception):
            raise response
        return response

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._respond(path, payload)

    def post_multipart(self, path: str, files: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        return self._respond(path, (files, data))


def _provider(**kwargs) -> HttpStage2VisionProvider:
    return HttpStage2VisionProvider(
        transport=StubTransport(**kwargs),
        embedding_space_id=SPACE,
        model_version=MODEL,
    )


# --- /v1/embed --------------------------------------------------------------


def test_embed_maps_real_shape_and_reports_dimension():
    provider = _provider(
        responses={"/v1/embed": {"embedding": [0.5] * 256, "embedding_space_id": SPACE,
                                 "model_version": MODEL, "normalized": True}}
    )
    result = provider.embed(image_bytes=b"fake", modality="loose_pill")
    assert result.dimension == 256
    assert result.embedding_space_id == SPACE
    assert result.normalized is True


def test_embed_rejects_non_finite_values():
    provider = _provider(
        responses={"/v1/embed": {"embedding": [float("nan")] * 256,
                                 "embedding_space_id": SPACE, "model_version": MODEL}}
    )
    with pytest.raises(VisionSchemaError):
        provider.embed(image_bytes=b"fake", modality="loose_pill")


def test_embed_rejects_wrong_dimension_because_gallery_must_be_reembedded():
    provider = _provider(
        responses={"/v1/embed": {"embedding": [0.1] * 128,
                                 "embedding_space_id": SPACE, "model_version": MODEL}}
    )
    with pytest.raises(ModelVersionMismatch):
        provider.embed(image_bytes=b"fake", modality="loose_pill")


def test_embed_rejects_model_version_drift():
    provider = _provider(
        responses={"/v1/embed": {"embedding": [0.1] * 256,
                                 "embedding_space_id": SPACE, "model_version": "different"}}
    )
    with pytest.raises(ModelVersionMismatch):
        provider.embed(image_bytes=b"fake", modality="loose_pill")


def test_embed_rejects_non_loose_pill_modality():
    provider = _provider(responses={})
    with pytest.raises(UnsupportedModality):
        provider.embed(image_bytes=b"fake", modality="blister")  # type: ignore[arg-type]


def test_embed_timeout_maps_to_unavailable_never_to_a_result():
    provider = _provider(raise_timeout=True)
    with pytest.raises(VisionUnavailable):
        provider.embed(image_bytes=b"fake", modality="loose_pill")


# --- /v1/match --------------------------------------------------------------


def _gallery(space: str = SPACE) -> list[GalleryReference]:
    return [
        GalleryReference(
            medication_id="med-1",
            name="Metformin 500 mg",
            embeddings=[[0.1] * 256],
            embedding_space_id=space,
        )
    ]


def test_match_returns_decision_without_inventing_a_similarity_score():
    provider = _provider(responses={"/v1/match": {"pills": [{"decision": "match", "medication_id": "med-1"}]}})
    outcome = provider.match(queries=[[0.1] * 256], gallery=_gallery())
    assert outcome.decision == "match"
    assert outcome.medication_id == "med-1"
    # The documented API exposes no score; the adapter must not fabricate one.
    assert outcome.score is None
    assert outcome.margin is None


def test_match_unknown_and_ambiguous_are_distinct_from_unavailable():
    for decision in ("unknown", "ambiguous"):
        provider = _provider(responses={"/v1/match": {"pills": [{"decision": decision}]}})
        outcome = provider.match(queries=[[0.1] * 256], gallery=_gallery())
        assert outcome.decision == decision
        assert outcome.medication_id is None


def test_match_timeout_is_never_reported_as_unmatched():
    provider = _provider(raise_timeout=True)
    with pytest.raises(VisionUnavailable):
        provider.match(queries=[[0.1] * 256], gallery=_gallery())


def test_match_rejects_unsupported_decision_value():
    provider = _provider(responses={"/v1/match": {"pills": [{"decision": "confident_identity"}]}})
    with pytest.raises(VisionSchemaError):
        provider.match(queries=[[0.1] * 256], gallery=_gallery())


def test_match_rejects_gallery_from_a_different_embedding_space():
    provider = _provider(responses={"/v1/match": {"pills": [{"decision": "match"}]}})
    with pytest.raises(ModelVersionMismatch):
        provider.match(queries=[[0.1] * 256], gallery=_gallery(space="other-space"))


def test_match_requires_queries_and_gallery():
    provider = _provider(responses={"/v1/match": {"pills": [{"decision": "match"}]}})
    with pytest.raises(VisionSchemaError):
        provider.match(queries=[], gallery=_gallery())
    with pytest.raises(VisionSchemaError):
        provider.match(queries=[[0.1] * 256], gallery=[])


# --- /v1/scan regression ----------------------------------------------------


def test_single_pill_returning_two_boxes_is_flagged_duplicate_and_not_countable():
    """Regression for the known user-reported TEVA single-pill -> 2 overlapping boxes."""
    provider = _provider(
        responses={
            "/v1/scan": {
                "pill_count": 1,
                "boxes": [
                    {"x": 0.10, "y": 0.10, "w": 0.40, "h": 0.40, "score": 0.91},
                    {"x": 0.15, "y": 0.12, "w": 0.38, "h": 0.39, "score": 0.77},
                ],
            }
        }
    )
    diagnostics = provider.scan_diagnostics(image_bytes=b"fake")
    assert diagnostics.pill_count == 1
    assert diagnostics.duplicate_boxes is True
    assert diagnostics.overlapping_boxes is True
    # Counts derived from /scan must not be trusted for automated dose counting.
    assert diagnostics.usable_for_dose_count is False


def test_scan_without_geometry_does_not_claim_overlap():
    provider = _provider(
        responses={"/v1/scan": {"pill_count": 2, "boxes": [{}, {}]}}
    )
    diagnostics = provider.scan_diagnostics(image_bytes=b"fake")
    assert diagnostics.pill_count == 2
    assert diagnostics.overlapping_boxes is False
    assert diagnostics.usable_for_dose_count is False


def test_scan_timeout_maps_to_unavailable():
    provider = _provider(raise_timeout=True)
    with pytest.raises(VisionUnavailable):
        provider.scan_diagnostics(image_bytes=b"fake")


def test_has_overlap_math_is_measured_only():
    assert _has_overlap([ScanBox(x=0.0, y=0.0, w=0.5, h=0.5), ScanBox(x=0.2, y=0.2, w=0.5, h=0.5)])
    assert not _has_overlap([ScanBox(x=0.0, y=0.0, w=0.2, h=0.2), ScanBox(x=0.5, y=0.5, w=0.2, h=0.2)])
    assert not _has_overlap([ScanBox(), ScanBox(x=0.1, y=0.1, w=0.2, h=0.2)])


# --- /v1/identify -----------------------------------------------------------


def test_identify_returns_candidates_marked_as_visual_possibilities():
    provider = _provider(
        responses={
            "/v1/identify": {
                "candidates": [
                    {"pill_id": "c3pi-1", "name": "Metformin 500 mg", "score": 0.88, "market": "US"},
                    {"pill_id": "c3pi-2", "name": "Metformin 850 mg", "score": 0.71, "market": "US"},
                ]
            }
        }
    )
    candidates = provider.identify_candidates(image_bytes=b"fake", top_k=5)
    assert [c.external_catalogue_id for c in candidates] == ["c3pi-1", "c3pi-2"]
    assert all(c.market == "US" for c in candidates)
    # A similarity is a number, never a probability claim.
    assert candidates[0].visual_similarity == pytest.approx(0.88)


def test_identify_respects_top_k():
    provider = _provider(
        responses={"/v1/identify": {"candidates": [{"pill_id": f"c-{i}"} for i in range(10)]}}
    )
    assert len(provider.identify_candidates(image_bytes=b"fake", top_k=3)) == 3


def test_identify_timeout_maps_to_unavailable():
    provider = _provider(raise_timeout=True)
    with pytest.raises(VisionUnavailable):
        provider.identify_candidates(image_bytes=b"fake")


# --- embedding space guard --------------------------------------------------


def test_embedding_space_guard_rejects_mixed_versions():
    space = EmbeddingSpace(SPACE, MODEL, 256)
    space.assert_compatible(space_id=SPACE, model_version=MODEL, dimension=256)
    with pytest.raises(ModelVersionMismatch):
        space.assert_compatible(space_id=SPACE, model_version="other", dimension=256)
    with pytest.raises(ModelVersionMismatch):
        space.assert_compatible(space_id="other", model_version=MODEL, dimension=256)
    with pytest.raises(ModelVersionMismatch):
        space.assert_compatible(space_id=SPACE, model_version=MODEL, dimension=128)


# --- SIMULATED provider -----------------------------------------------------


def test_fake_provider_is_explicitly_marked_simulated():
    fake = FakeVisionProvider()
    assert fake.SIMULATED is True
    outcome = fake.match(queries=[[0.1] * 256], gallery=_gallery(space=fake.embedding_space_id))
    assert "SIMULATED" in outcome.quality_flags
    assert outcome.provenance == ["SIMULATED:fake_vision_provider"]

    embedding = fake.embed(image_bytes=b"abc", modality="loose_pill")
    assert embedding.embedding_space_id == FakeVisionProvider.embedding_space_id
    assert embedding.dimension == 256


def test_fake_provider_can_simulate_unavailability_but_never_fake_success():
    fake = FakeVisionProvider(raise_unavailable=True)
    with pytest.raises(VisionUnavailable):
        fake.match(queries=[[0.1] * 256], gallery=[])
    with pytest.raises(VisionUnavailable):
        fake.scan_diagnostics(image_bytes=b"x")


def test_fake_provider_reproduces_the_known_duplicate_box_regression():
    fake = FakeVisionProvider(
        declared_pill_count=1,
        boxes=[
            ScanBox(x=0.1, y=0.1, w=0.4, h=0.4),
            ScanBox(x=0.15, y=0.12, w=0.38, h=0.39),
        ],
    )
    diagnostics = fake.scan_diagnostics(image_bytes=b"x")
    assert diagnostics.duplicate_boxes is True
    assert diagnostics.usable_for_dose_count is False


def test_fake_provider_candidates_are_not_real_identities():
    fake = FakeVisionProvider(
        candidates=[PillCandidate(external_catalogue_id="fake-1", display_name="SIMULATED candidate")]
    )
    candidates = fake.identify_candidates(image_bytes=b"x")
    assert candidates[0].display_name == "SIMULATED candidate"
    assert candidates[0].external_catalogue_id.startswith("fake-")
