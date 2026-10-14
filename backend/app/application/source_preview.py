"""Read-only extraction preview; source text never becomes dosing authority."""

from threading import Lock
from typing import Literal

from ..contracts.ports import IdGenerator
from ..contracts.source_extraction import MedicationSourceExtractionDTO, SourceExtractionPort
from ..domain.errors import ValidationError


class SourcePreviewService:
    def __init__(self, *, provider: SourceExtractionPort, ids: IdGenerator) -> None:
        self._provider, self._ids = provider, ids
        self._inflight = Lock()

    def preview(
        self,
        *,
        content: bytes,
        source_kind: Literal["package", "pharmacy_label", "prescription"],
        consent: bool,
        demo_only: bool,
    ) -> MedicationSourceExtractionDTO:
        if not consent or not demo_only:
            raise ValidationError("Only consented synthetic demo images may be sent for extraction")
        if not self._inflight.acquire(blocking=False):
            from ..domain.errors import ProviderUnavailableError

            raise ProviderUnavailableError("A label preview is already in progress; please retry later")
        try:
            return self._provider.extract_medication_source(
                source_document_id=self._ids.new_id(), source_kind=source_kind, image_bytes=content
            )
        finally:
            self._inflight.release()
