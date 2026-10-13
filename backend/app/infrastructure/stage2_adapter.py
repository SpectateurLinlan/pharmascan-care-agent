"""v0.8.0 Stage2 anti-corruption adapter; fixtures are NOT model evaluation.

Only injected transports/schema are used. No database, safety-authority or source
activation. Legacy undocumented aliases and silent metadata fallbacks removed.
"""

from __future__ import annotations

import json
import math
from typing import Literal, TypeVar

from app.contracts.vision import (
    EmbeddingResult,
    GalleryReference,
    MatchDecision,
    MatchOutcome,
    ModelMetadata,
    ModelVersionMismatch,
    PillCandidate,
    ReferenceSimilarity,
    ScanBox,
    ScanDiagnostics,
    UnsupportedModality,
    VisionSchemaError,
    VisionUnavailable,
)
from app.infrastructure.stage2_http import HttpTransport
from app.infrastructure.stage2_schema import Stage2Contract
from app.infrastructure.stage2_wire import (
    DetectionWire,
    EmbeddingWire,
    IdentifyWire,
    MatchWire,
    ModelInfoWire,
    ScanWire,
    Wire,
)
from pydantic import ValidationError

W = TypeVar("W", bound=Wire)


def project(contract: Stage2Contract, name: str, payload: object, wire: type[W]) -> W:
    valid = contract.validate(name, payload)
    try:
        return wire.model_validate(valid)
    except ValidationError as exc:
        raise VisionSchemaError(f"Stage2 {name} invalid typed fields") from exc


def _validate_vector(vector: list[float]) -> None:
    if len(vector) != 256:
        raise ModelVersionMismatch("embedding dimension must be 256 for this integration baseline")
    if not all(type(v) in (int, float) and math.isfinite(v) for v in vector):
        raise VisionSchemaError("embedding contains invalid/non-finite values")


def boxes_overlap(boxes: list[ScanBox]) -> bool:
    """Public geometry utility: measured pixel overlap, not pill identity."""
    for i, first in enumerate(boxes):
        if first.x is None or first.y is None or first.w is None or first.h is None:
            continue
        for second in boxes[i + 1 :]:
            if second.x is None or second.y is None or second.w is None or second.h is None:
                continue
            if min(first.x + first.w, second.x + second.w) > max(first.x, second.x) and min(
                first.y + first.h, second.y + second.h
            ) > max(first.y, second.y):
                return True
    return False


def detection_dto(wire: DetectionWire, **extra: object) -> ScanDiagnostics:
    if wire.pill_count < 0 or len(wire.box_flags) != len(wire.boxes):
        raise VisionSchemaError("invalid detection count/flag alignment")
    boxes = []
    for coords in wire.boxes:
        if len(coords) != 4 or not all(math.isfinite(v) and v >= 0 for v in coords):
            raise VisionSchemaError("detection requires finite nonnegative pixel xyxy")
        x0, y0, x1, y1 = coords
        if x1 <= x0 or y1 <= y0:
            raise VisionSchemaError("detection box has invalid pixel extent")
        boxes.append(ScanBox(x=x0, y=y0, w=x1 - x0, h=y1 - y0))
    overlap = boxes_overlap(boxes)
    return ScanDiagnostics(
        pill_count=wire.pill_count,
        boxes=boxes,
        box_flags=wire.box_flags,
        provider_count_reliable=wire.count_reliable,
        flags=wire.flags,
        found_by=wire.found_by,
        duplicate_boxes=overlap or (wire.pill_count == 1 and len(boxes) > 1),
        overlapping_boxes=overlap,
        usable_for_dose_count=False,
        **extra,
    )


class HttpStage2VisionProvider:
    EXPECTED_DIMENSION = 256

    def __init__(
        self,
        *,
        transport: HttpTransport,
        contract: Stage2Contract,
        embedding_space_id: str,
        model_version: str,
        preprocessing_version: str,
    ) -> None:
        if not all((embedding_space_id, model_version, preprocessing_version)):
            raise ValueError("explicit expected model/space/preprocessing required")
        self._transport, self._contract = transport, contract
        self._space_id, self._model_version = embedding_space_id, model_version
        self._preprocess = preprocessing_version

    def _check_versions(self, space: str, model: str, preprocess: str | None = None) -> None:
        if (space, model) != (self._space_id, self._model_version):
            raise ModelVersionMismatch("provider embedding space/model drift")
        if preprocess is not None and preprocess != self._preprocess:
            raise ModelVersionMismatch("provider preprocessing drift")

    def model_info(self) -> ModelMetadata:
        wire = project(self._contract, "ModelInfo", self._transport.get_json("/v1/model-info"), ModelInfoWire)
        self._check_versions(wire.embedding_space_id, wire.model_version, wire.preprocess_version)
        if wire.api_version != "0.8.0" or wire.embedding_dim != 256:
            raise ModelVersionMismatch("provider API version/dimension changed")
        return ModelMetadata(
            api_version=wire.api_version,
            model_version=wire.model_version,
            embedding_space_id=wire.embedding_space_id,
            preprocessing_version=wire.preprocess_version,
            dimension=wire.embedding_dim,
            normalized=wire.normalized,
            crop_window=wire.crop_window,
            threshold=wire.threshold,
            margin=wire.margin,
            calibration_json=json.dumps(wire.calibration, sort_keys=True),
            training_coverage=wire.training_coverage,
            known_limits=wire.known_limits,
        )

    def embed(self, *, image_bytes: bytes, modality: Literal["loose_pill"]) -> EmbeddingResult:
        if modality != "loose_pill":
            raise UnsupportedModality("package/blister cannot use the loose-pill embedding space")
        try:
            payload = self._transport.post_multipart("/v1/embed", {"image": image_bytes}, {})
        except TimeoutError as exc:
            raise VisionUnavailable("Stage2 embed timeout") from exc
        wire = project(self._contract, "Embedding", payload, EmbeddingWire)
        _validate_vector(wire.embedding)
        if wire.dim != len(wire.embedding):
            raise ModelVersionMismatch("embedding dim differs from actual vector length")
        self._check_versions(wire.embedding_space_id, wire.model_version, wire.preprocess_version)
        if wire.normalized and not math.isclose(sum(v * v for v in wire.embedding), 1.0, abs_tol=1e-3):
            raise VisionSchemaError("provider normalized declaration conflicts with vector norm")
        return EmbeddingResult(
            embedding=wire.embedding,
            dimension=wire.dim,
            embedding_space_id=wire.embedding_space_id,
            model_version=wire.model_version,
            preprocessing_version=wire.preprocess_version,
            normalized=wire.normalized,
            imprint_reads=wire.imprint_reads,
            text_reading=wire.text_reading,
        )

    def match(self, *, queries: list[EmbeddingResult], gallery: list[GalleryReference]) -> MatchOutcome:
        # Existing public result is one dose-check outcome: do not silently drop multi-query results.
        if len(queries) != 1 or not gallery:
            raise VisionSchemaError("single-pill match requires one typed query and a nonempty gallery")
        for query in queries:
            if not isinstance(query, EmbeddingResult):
                raise VisionSchemaError("query requires typed embedding metadata, not a bare vector")
            self._check_versions(query.embedding_space_id, query.model_version, query.preprocessing_version)
            _validate_vector(query.embedding)
            if query.dimension != 256:
                raise ModelVersionMismatch("query dimension declaration mismatch")
        for ref in gallery:
            if not isinstance(ref, GalleryReference):
                raise VisionSchemaError("gallery requires typed reference metadata")
            self._check_versions(ref.embedding_space_id, ref.model_version, ref.preprocessing_version)
            if not ref.embeddings:
                raise VisionSchemaError("gallery reference has no vectors")
            for vector in ref.embeddings:
                _validate_vector(vector)
        request = {
            "queries": [q.embedding for q in queries],
            "gallery": [
                {"medication_id": r.medication_id, "name": r.name, "embeddings": r.embeddings, "imprint": r.imprint}
                for r in gallery
            ],
            "model_version": self._model_version,
            "embedding_space_id": self._space_id,
        }
        self._contract.validate("MatchRequest", request)
        try:
            payload = self._transport.post_json("/v1/match", request)
        except TimeoutError as exc:
            raise VisionUnavailable("Stage2 match timeout") from exc
        wire = project(self._contract, "MatchResponse", payload, MatchWire)
        self._check_versions(wire.embedding_space_id, wire.model_version)
        if len(wire.results) != 1:
            raise VisionSchemaError("match result/query cardinality mismatch")
        item = wire.results[0]
        ids = {r.medication_id for r in gallery}
        if item.closest.medication_id not in ids or (item.runner_up and item.runner_up.medication_id not in ids):
            raise VisionSchemaError("provider referred to a medication outside the supplied gallery")
        if item.decision == "match" and (not item.medication_id or item.medication_id not in ids):
            raise VisionSchemaError("matched medication is missing or outside gallery")
        if item.decision != "match" and item.medication_id is not None:
            raise VisionSchemaError("nonmatch must not attach a confirmed medication")
        return MatchOutcome(
            decision=item.decision,
            medication_id=item.medication_id,
            score=item.similarity,
            threshold=wire.threshold,
            margin=wire.margin,
            closest=ReferenceSimilarity(
                medication_id=item.closest.medication_id, name=item.closest.name, score=item.closest.similarity
            ),
            runner_up=(
                ReferenceSimilarity(
                    medication_id=item.runner_up.medication_id,
                    name=item.runner_up.name,
                    score=item.runner_up.similarity,
                )
                if item.runner_up
                else None
            ),
            model_version=wire.model_version,
            embedding_space_id=wire.embedding_space_id,
            limits=wire.limits,
            provenance=["stage2:v0.8.0:/v1/match"],
        )

    def detect(self, *, image_bytes: bytes) -> ScanDiagnostics:
        try:
            payload = self._transport.post_multipart("/v1/detect", {"image": image_bytes}, {})
        except TimeoutError as exc:
            raise VisionUnavailable("Stage2 detect timeout") from exc
        wire = project(self._contract, "DetectResponse", payload, DetectionWire)
        return detection_dto(wire, input_abstained=bool(wire.input_check and wire.input_check.abstained))

    def scan_diagnostics(self, *, image_bytes: bytes) -> ScanDiagnostics:
        try:
            payload = self._transport.post_multipart("/v1/scan", {"image": image_bytes}, {"input_type": "loose_pills"})
        except TimeoutError as exc:
            raise VisionUnavailable("Stage2 scan timeout") from exc
        wire = project(self._contract, "ScanResponse", payload, ScanWire)
        if wire.model_version != self._model_version:
            raise ModelVersionMismatch("scan model version drift")
        return detection_dto(
            wire.detection,
            model_version=wire.model_version,
            input_abstained=bool(wire.input_check and wire.input_check.abstained),
            text_reading=wire.text_reading,
            limits=wire.limits,
        )

    def identify_candidates(self, *, image_bytes: bytes, top_k: int = 5) -> list[PillCandidate]:
        if type(top_k) is not int or not 1 <= top_k <= 10:
            raise VisionSchemaError("top_k must be between 1 and 10")
        try:
            payload = self._transport.post_multipart("/v1/identify", {"images": image_bytes}, {"top_k": str(top_k)})
        except TimeoutError as exc:
            raise VisionUnavailable("Stage2 identify timeout") from exc
        wire = project(self._contract, "IdentifyResponse", payload, IdentifyWire)
        if wire.model_version != self._model_version:
            raise ModelVersionMismatch("identify model version drift")
        if wire.input_check and wire.input_check.abstained:
            return []
        return [
            PillCandidate(
                external_catalogue_id=c.pill_id,
                display_name=c.name,
                brand=c.brand,
                strength=c.strength,
                form=c.dose_form,
                rxcui=c.rxcui,
                ingredients=c.ingredients,
                market=c.market,
                visual_similarity=c.similarity,
                source_dataset="NLM C3PI",
                model_version=wire.model_version,
                limits=wire.limits,
            )
            for c in wire.candidates[:top_k]
        ]


class FakeVisionProvider:
    """SIMULATED deterministic stand-in, never reports live recognition."""

    SIMULATED = True
    embedding_space_id = "SIMULATED-space-v0"
    model_version = "SIMULATED-model-v0"
    preprocessing_version = "SIMULATED-preprocess-v0"

    def __init__(
        self,
        *,
        decision: MatchDecision = "unknown",
        medication_id: str | None = None,
        dimension: int = 256,
        boxes: list[ScanBox] | None = None,
        candidates: list[PillCandidate] | None = None,
        raise_unavailable: bool = False,
        declared_pill_count: int | None = None,
    ) -> None:
        self._decision, self._medication_id, self._dimension = decision, medication_id, dimension
        self._boxes, self._candidates = boxes or [], candidates or []
        self._raise_unavailable, self._count = raise_unavailable, declared_pill_count

    def _check(self) -> None:
        if self._raise_unavailable:
            raise VisionUnavailable("SIMULATED provider unavailable")

    def model_info(self) -> ModelMetadata:
        self._check()
        return ModelMetadata(
            api_version="SIMULATED",
            model_version=self.model_version,
            embedding_space_id=self.embedding_space_id,
            preprocessing_version=self.preprocessing_version,
            dimension=self._dimension,
            normalized=False,
            crop_window=0,
            threshold=0,
            margin=0,
            calibration_json="{}",
            training_coverage="SIMULATED",
            known_limits=["Not a model"],
        )

    def embed(self, *, image_bytes: bytes, modality: Literal["loose_pill"]) -> EmbeddingResult:
        self._check()
        if modality != "loose_pill":
            raise UnsupportedModality("SIMULATED loose pill only")
        return EmbeddingResult(
            embedding=[0.0] * self._dimension,
            dimension=self._dimension,
            embedding_space_id=self.embedding_space_id,
            model_version=self.model_version,
            preprocessing_version=self.preprocessing_version,
            normalized=False,
            provider_request_id="SIMULATED",
        )

    def match(self, *, queries: list[EmbeddingResult], gallery: list[GalleryReference]) -> MatchOutcome:
        self._check()
        return MatchOutcome(
            decision=self._decision,
            medication_id=self._medication_id,
            model_version=self.model_version,
            quality_flags=["SIMULATED"],
            provenance=["SIMULATED:fake_vision_provider"],
        )

    def scan_diagnostics(self, *, image_bytes: bytes) -> ScanDiagnostics:
        self._check()
        overlap = boxes_overlap(self._boxes)
        return ScanDiagnostics(
            pill_count=self._count if self._count is not None else len(self._boxes),
            boxes=self._boxes,
            duplicate_boxes=overlap,
            overlapping_boxes=overlap,
            model_version=self.model_version,
        )

    def detect(self, *, image_bytes: bytes) -> ScanDiagnostics:
        return self.scan_diagnostics(image_bytes=image_bytes)

    def identify_candidates(self, *, image_bytes: bytes, top_k: int = 5) -> list[PillCandidate]:
        self._check()
        return self._candidates[:top_k]


__all__ = ["FakeVisionProvider", "HttpStage2VisionProvider", "HttpTransport", "boxes_overlap"]
