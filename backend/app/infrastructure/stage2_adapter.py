"""Stage2 HTTP adapter + explicitly SIMULATED fake provider.

The HTTP adapter maps the *documented* v0.4.0 contract (docs/pharmascan-api-openapi.json)
onto the internal DTOs. It performs no inference of its own and refuses to
fabricate fields the API does not return.

** BLOCKED / SIMULATED **
- `HttpStage2VisionProvider` is written against OpenAPI v0.4.0 only; the live
  deploy may differ (B01). Its tests use a stubbed transport, so they prove
  mapping and failure handling — NOT that the real service behaves this way.
- `FakeVisionProvider` is a deterministic stand-in and MUST stay clearly
  labelled. It is never reported as a real recognition result.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from .vision_contracts import (
    EmbeddingResult,
    GalleryReference,
    MatchOutcome,
    ModelVersionMismatch,
    PillCandidate,
    ScanBox,
    ScanDiagnostics,
    UnsupportedModality,
    VisionSchemaError,
    VisionUnavailable,
)


class HttpTransport:
    """Minimal injected transport so the adapter never owns a global client."""

    def __init__(self, *, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "Inject a real HTTP transport (e.g. httpx) at the composition root"
        )

    def post_multipart(self, path: str, files: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "Inject a real HTTP transport (e.g. httpx) at the composition root"
        )


class HttpStage2VisionProvider:
    """Stage2 client. Maps real JSON -> internal DTOs at ONE boundary.

    ``transport`` is injected (AGENTS.md rule 2); there is no module-level
    client, session or token.
    """

    #: Expected only if the live API confirms it (AGENTS.md rule 15).
    EXPECTED_DIMENSION = 256

    def __init__(
        self,
        *,
        transport: HttpTransport,
        embedding_space_id: str,
        model_version: str,
        max_retries: int = 2,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self._transport = transport
        self._space_id = embedding_space_id
        self._model_version = model_version
        self._max_retries = max_retries

    # -- /v1/embed -----------------------------------------------------------

    def embed(self, *, image_bytes: bytes, modality: Literal["loose_pill"]) -> EmbeddingResult:
        if modality != "loose_pill":
            raise UnsupportedModality(
                "only loose-pill crops belong in the loose-pill embedding space"
            )
        try:
            payload = self._transport.post_multipart(
                "/v1/embed", files={"file": image_bytes}, data={}
            )
        except TimeoutError as exc:
            raise VisionUnavailable(f"/v1/embed timed out: {exc}") from exc

        embedding = payload.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise VisionSchemaError("/v1/embed returned no embedding array")
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in embedding):
            raise VisionSchemaError("embedding contains non-finite values")
        dimension = len(embedding)

        space_id = str(payload.get("embedding_space_id") or self._space_id)
        model_version = str(payload.get("model_version") or self._model_version)
        if space_id != self._space_id or model_version != self._model_version:
            raise ModelVersionMismatch(
                f"adapter configured for {self._space_id}/{self._model_version}, "
                f"provider reported {space_id}/{model_version}"
            )
        if dimension != self.EXPECTED_DIMENSION:
            # Not fatal by itself, but must be surfaced: a dimension change
            # invalidates every stored gallery embedding.
            raise ModelVersionMismatch(
                f"embedding dimension {dimension} != expected {self.EXPECTED_DIMENSION}; "
                "gallery must be re-embedded before any matching"
            )
        return EmbeddingResult(
            embedding=[float(v) for v in embedding],
            dimension=dimension,
            embedding_space_id=space_id,
            model_version=model_version,
            normalized=payload.get("normalized"),
            provider_request_id=payload.get("request_id"),
        )

    # -- /v1/match -----------------------------------------------------------

    def match(
        self, *, queries: list[list[float]], gallery: list[GalleryReference]
    ) -> MatchOutcome:
        if not queries:
            raise VisionSchemaError("at least one query embedding is required")
        if not gallery:
            raise VisionSchemaError("at least one gallery reference is required")

        for reference in gallery:
            if reference.embedding_space_id != self._space_id:
                raise ModelVersionMismatch(
                    f"gallery reference {reference.medication_id} belongs to embedding space "
                    f"{reference.embedding_space_id}, expected {self._space_id}"
                )
            for vector in reference.embeddings:
                if len(vector) != len(queries[0]):
                    raise ModelVersionMismatch(
                        "gallery and query vectors have different dimensions"
                    )

        payload = {
            "queries": queries,
            "gallery": [
                {
                    "medication_id": r.medication_id,
                    "name": r.name,
                    "embeddings": r.embeddings,
                }
                for r in gallery
            ],
            "model_version": self._model_version,
        }
        try:
            response = self._transport.post_json("/v1/match", payload)
        except TimeoutError as exc:
            # A timeout must NEVER be reported as "unmatched".
            raise VisionUnavailable(f"/v1/match timed out: {exc}") from exc

        pills = response.get("pills")
        if not isinstance(pills, list) or not pills:
            raise VisionSchemaError("/v1/match returned no pills array")
        first = pills[0]
        if not isinstance(first, dict):
            raise VisionSchemaError("/v1/match pill entry is not an object")

        decision = first.get("decision")
        if decision not in ("match", "unknown", "ambiguous"):
            raise VisionSchemaError(f"/v1/match returned unsupported decision {decision!r}")

        return MatchOutcome(
            decision=decision,
            medication_id=first.get("medication_id"),
            # The v0.4.0 contract exposes no similarity score: leave it None
            # rather than inventing a probability.
            score=None,
            margin=None,
            model_version=self._model_version,
            provenance=["stage2:/v1/match"],
        )

    # -- /v1/scan (diagnostics only) -----------------------------------------

    def scan_diagnostics(self, *, image_bytes: bytes) -> ScanDiagnostics:
        try:
            payload = self._transport.post_multipart(
                "/v1/scan", files={"file": image_bytes}, data={}
            )
        except TimeoutError as exc:
            raise VisionUnavailable(f"/v1/scan timed out: {exc}") from exc

        raw_boxes = payload.get("boxes") or payload.get("detections") or []
        boxes: list[ScanBox] = []
        if isinstance(raw_boxes, list):
            for raw in raw_boxes:
                if isinstance(raw, dict):
                    boxes.append(
                        ScanBox(
                            x=_as_float(raw.get("x") or raw.get("x1")),
                            y=_as_float(raw.get("y") or raw.get("y1")),
                            w=_as_float(raw.get("w")),
                            h=_as_float(raw.get("h")),
                            score=_as_float(raw.get("score")),
                        )
                    )

        pill_count = payload.get("pill_count")
        if not isinstance(pill_count, int):
            pill_count = len(boxes)

        duplicate = pill_count == 1 and len(boxes) > 1
        overlapping = _has_overlap(boxes)
        return ScanDiagnostics(
            pill_count=pill_count,
            boxes=boxes,
            duplicate_boxes=duplicate,
            overlapping_boxes=overlapping,
            # Never usable for automated dose counting until the known
            # single-pill duplicate-box regression is independently fixed.
            usable_for_dose_count=False,
            raw_decision=payload.get("decision"),
            model_version=self._model_version,
        )

    # -- /v1/identify --------------------------------------------------------

    def identify_candidates(self, *, image_bytes: bytes, top_k: int = 5) -> list[PillCandidate]:
        try:
            payload = self._transport.post_multipart(
                "/v1/identify", files={"file": image_bytes}, data={"top_k": str(top_k)}
            )
        except TimeoutError as exc:
            raise VisionUnavailable(f"/v1/identify timed out: {exc}") from exc

        raw = payload.get("candidates") or payload.get("matches") or []
        if not isinstance(raw, list):
            raise VisionSchemaError("/v1/identify candidates is not a list")
        candidates: list[PillCandidate] = []
        for item in raw[:top_k]:
            if not isinstance(item, dict):
                continue
            candidates.append(
                PillCandidate(
                    external_catalogue_id=str(item.get("pill_id") or item.get("id") or ""),
                    display_name=item.get("name") or item.get("display_name"),
                    brand=item.get("brand"),
                    strength=item.get("strength"),
                    form=item.get("form"),
                    market=str(item.get("market") or "US"),
                    visual_similarity=_as_float(item.get("score") or item.get("similarity")),
                    source_dataset=item.get("source_dataset") or "stage2_catalogue",
                )
            )
        return candidates


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _has_overlap(boxes: list[ScanBox]) -> bool:
    """Measured overlap only; boxes missing geometry cannot be assessed."""
    for i, first in enumerate(boxes):
        if None in (first.x, first.y, first.w, first.h):
            continue
        for second in boxes[i + 1 :]:
            if None in (second.x, second.y, second.w, second.h):
                continue
            x_overlap = max(0.0, min(first.x + first.w, second.x + second.w) - max(first.x, second.x))
            y_overlap = max(0.0, min(first.y + first.h, second.y + second.h) - max(first.y, second.y))
            if x_overlap > 0 and y_overlap > 0:
                return True
    return False


class FakeVisionProvider:
    """** SIMULATED ** deterministic stand-in for the Stage2 service.

    Used only in tests and in clearly-labelled degraded demo mode. It is NOT
    a model and its outputs MUST NOT be presented as recognition results.
    """

    SIMULATED = True
    embedding_space_id = "SIMULATED-space-v0"
    model_version = "SIMULATED-model-v0"

    def __init__(
        self,
        *,
        decision: str = "unknown",
        medication_id: str | None = None,
        dimension: int = 256,
        boxes: list[ScanBox] | None = None,
        candidates: list[PillCandidate] | None = None,
        raise_unavailable: bool = False,
        declared_pill_count: int | None = None,
    ) -> None:
        self._decision = decision
        self._medication_id = medication_id
        self._dimension = dimension
        self._boxes = boxes or []
        self._candidates = candidates or []
        self._raise_unavailable = raise_unavailable
        self._declared_pill_count = declared_pill_count

    def embed(self, *, image_bytes: bytes, modality: Literal["loose_pill"]) -> EmbeddingResult:
        if modality != "loose_pill":
            raise UnsupportedModality("SIMULATED provider only supports loose_pill")
        if self._raise_unavailable:
            raise VisionUnavailable("SIMULATED provider is marked unavailable")
        # Deterministic, non-learned vector derived from input length.
        seed = float(len(image_bytes) % 97) / 97.0
        vector = [seed] * self._dimension
        return EmbeddingResult(
            embedding=vector,
            dimension=self._dimension,
            embedding_space_id=self.embedding_space_id,
            model_version=self.model_version,
            normalized=False,
            provider_request_id="SIMULATED-embed",
        )

    def match(
        self, *, queries: list[list[float]], gallery: list[GalleryReference]
    ) -> MatchOutcome:
        if self._raise_unavailable:
            raise VisionUnavailable("SIMULATED provider is marked unavailable")
        return MatchOutcome(
            decision=self._decision,  # type: ignore[arg-type]
            medication_id=self._medication_id,
            score=None,
            model_version=self.model_version,
            quality_flags=("SIMULATED",),
            provenance=["SIMULATED:fake_vision_provider"],
        )

    def scan_diagnostics(self, *, image_bytes: bytes) -> ScanDiagnostics:
        if self._raise_unavailable:
            raise VisionUnavailable("SIMULATED provider is marked unavailable")
        count = self._declared_pill_count if self._declared_pill_count is not None else len(self._boxes)
        # Mirrors the known real regression: one pill declared, several boxes
        # returned -> duplicate/overlapping detections.
        duplicate = count == 1 and len(self._boxes) > 1
        return ScanDiagnostics(
            pill_count=count,
            boxes=list(self._boxes),
            duplicate_boxes=duplicate,
            overlapping_boxes=_has_overlap(self._boxes),
            usable_for_dose_count=False,
            model_version=self.model_version,
        )

    def identify_candidates(self, *, image_bytes: bytes, top_k: int = 5) -> list[PillCandidate]:
        if self._raise_unavailable:
            raise VisionUnavailable("SIMULATED provider is marked unavailable")
        return list(self._candidates)[:top_k]
