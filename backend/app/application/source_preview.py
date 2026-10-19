"""Read-only extraction preview; source text never becomes dosing authority."""

from threading import Lock
from typing import Literal

from ..contracts.ports import IdGenerator
from ..contracts.source_extraction import (
    ImageRoute,
    ImageRoutingPort,
    ListedMedication,
    MedicationSourceExtractionDTO,
    SourceExtractionPort,
)
from ..domain.errors import ValidationError


class SourcePreviewService:
    def __init__(
        self, *, provider: SourceExtractionPort, ids: IdGenerator, routing: ImageRoutingPort | None = None
    ) -> None:
        self._provider, self._ids = provider, ids
        self._inflight = Lock()
        self._routing = routing

    def route(self, *, content: bytes, consent: bool, demo_only: bool) -> ImageRoute:
        if not consent:
            raise ValidationError("Agree to image processing before reading this photo")
        if self._routing is None:
            from ..domain.errors import ProviderUnavailableError

            raise ProviderUnavailableError("Choose the source type yourself")
        return self._routing.route_image(content)

    def route_image(self, image: bytes, *, demo_only: bool) -> ImageRoute:
        """Expose the existing versioned input check to other application services."""
        return self.route(content=image, consent=True, demo_only=demo_only)

    def preview(
        self,
        *,
        content: bytes,
        source_kind: Literal["package", "pharmacy_label", "prescription"],
        consent: bool,
        demo_only: bool,
        medications: tuple[ListedMedication, ...] = (),
    ) -> MedicationSourceExtractionDTO:
        if not consent:
            raise ValidationError("Agree to image processing before reading this photo")
        if not self._inflight.acquire(blocking=False):
            from ..domain.errors import ProviderUnavailableError

            raise ProviderUnavailableError("A label preview is already in progress; please retry later")
        try:
            if medications:
                return self._provider.extract_medication_source(
                    source_document_id=self._ids.new_id(),
                    source_kind=source_kind,
                    image_bytes=content,
                    medications=medications,
                )
            return self._provider.extract_medication_source(
                source_document_id=self._ids.new_id(),
                source_kind=source_kind,
                image_bytes=content,
            )
        finally:
            self._inflight.release()
