"""Compatibility imports for existing callers; public DTOs live in contracts.

v0.8.0 mappings stay inside infrastructure. New application callers import
app.contracts.vision, never raw Stage2 wire schemas.
"""

from app.contracts.vision import (
    EmbeddingResult,
    EmbeddingSpace,
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
    VisionDTO,
    VisionError,
    VisionPort,
    VisionRequestError,
    VisionSchemaError,
    VisionUnavailable,
)

__all__ = [
    "EmbeddingResult",
    "EmbeddingSpace",
    "GalleryReference",
    "MatchDecision",
    "MatchOutcome",
    "ModelMetadata",
    "ModelVersionMismatch",
    "PillCandidate",
    "ReferenceSimilarity",
    "ScanBox",
    "ScanDiagnostics",
    "UnsupportedModality",
    "VisionDTO",
    "VisionError",
    "VisionPort",
    "VisionRequestError",
    "VisionSchemaError",
    "VisionUnavailable",
]
