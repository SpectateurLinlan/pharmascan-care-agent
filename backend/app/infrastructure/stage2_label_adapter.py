"""Preferred /v1/read-label provider. Not a generic OCR or regimen service."""

from typing import Literal
from uuid import UUID

from app.contracts.source_extraction import (
    ExtractedMedication,
    IngredientIdentity,
    MedicationSourceExtractionDTO,
    PrintedEvidence,
    ProductIdentity,
    RegimenEvidence,
    SourceListComparison,
)
from app.contracts.vision import UnsupportedModality, VisionUnavailable
from app.infrastructure.stage2_adapter import project
from app.infrastructure.stage2_http import HttpTransport
from app.infrastructure.stage2_schema import Stage2Contract
from app.infrastructure.stage2_wire import LabelWire, PrintedWire


def _printed(field: PrintedWire | None) -> PrintedEvidence | None:
    return PrintedEvidence(value=field.value, line=field.line) if field is not None else None


class PharmaScanLabelProvider:
    def __init__(self, *, transport: HttpTransport, contract: Stage2Contract) -> None:
        self._transport, self._contract = transport, contract

    def extract_medication_source(
        self,
        *,
        source_document_id: UUID,
        source_kind: Literal["package", "pharmacy_label", "prescription"],
        image_bytes: bytes,
    ) -> MedicationSourceExtractionDTO:
        if source_kind not in ("package", "pharmacy_label", "prescription"):
            raise UnsupportedModality("source extraction requires readable package/label/prescription")
        try:
            payload = self._transport.post_multipart("/v1/read-label", {"image": image_bytes}, {})
        except TimeoutError as exc:
            raise VisionUnavailable("Stage2 read-label timeout; use manual enrollment") from exc
        wire = project(self._contract, "ReadLabelResponse", payload, LabelWire)
        normalized = []
        for candidate in wire.candidates:
            fields = candidate.fields
            regimen_fields = ("directions", "quantity", "date", "expiry_date")
            absent = [name for name in regimen_fields if fields is None or getattr(fields, name) is None]
            nulls = [
                name
                for name in regimen_fields
                if fields is not None and name in fields.model_fields_set and getattr(fields, name) is None
            ]
            normalized.append(
                ExtractedMedication(
                    product=ProductIdentity(
                        name=candidate.name,
                        brand=candidate.brand,
                        ingredients=[IngredientIdentity(name=i.name, rxcui=i.rxcui) for i in candidate.ingredients],
                        strength=candidate.strength,
                        rxcui=candidate.rxcui,
                        rxnorm_name=candidate.rxnorm_name,
                        dose_form=_printed(fields.dose_form) if fields else None,
                        source_lines=candidate.found_in,
                        first_line=candidate.first_line,
                    ),
                    regimen_evidence=RegimenEvidence(
                        directions=_printed(fields.directions) if fields else None,
                        quantity=_printed(fields.quantity) if fields else None,
                        date=_printed(fields.date) if fields else None,
                        expiry_date=_printed(fields.expiry_date) if fields else None,
                        missing_fields=absent,
                        explicit_null_fields=nulls,
                    ),
                    list_comparison=(
                        SourceListComparison(
                            status=candidate.list_check.status,
                            medication_id=candidate.list_check.medication_id,
                            message=candidate.list_check.message,
                        )
                        if candidate.list_check
                        else None
                    ),
                )
            )
        return MedicationSourceExtractionDTO(
            source_document_id=source_document_id,
            source_kind=source_kind,
            provider_source=wire.source,
            extraction_model=wire.ocr_model,
            candidates=normalized,
            note=wire.note,
        )
