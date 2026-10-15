"""Reuse the versioned Stage2 label adapter with an owned per-call HTTP client."""

from collections.abc import Callable
from typing import Literal
from uuid import UUID

import httpx

from ..contracts.source_extraction import ImageRoute, ListedMedication, MedicationSourceExtractionDTO
from ..contracts.vision import VisionError, VisionRequestError, VisionSchemaError
from ..domain.errors import ProviderUnavailableError, ValidationError
from .stage2_http import HttpxStage2Transport, sanitize_image
from .stage2_label_adapter import PharmaScanLabelProvider
from .stage2_schema import Stage2Contract


class SourceGateway:
    def __init__(
        self, *, base_url: str, contract: Stage2Contract, client_factory: Callable[[], httpx.Client] = httpx.Client
    ) -> None:
        self._base_url, self._contract, self._factory = base_url, contract, client_factory

    def route_image(self, image: bytes) -> ImageRoute:
        try:
            with self._factory() as client:
                transport = HttpxStage2Transport(
                    client=client, contract=self._contract, base_url=self._base_url, get_retries=0, sleep=lambda _: None
                )
                payload = transport.post_multipart("/v1/check-input", {"image": image}, {})
                self._contract.validate("CheckInputResponse", payload)
                check = payload["input_check"]
                image_type = check["type"]
                workflow = (
                    "source_review"
                    if image_type in {"package", "printed", "document"}
                    else ("pill_evidence" if image_type == "loose_pills" and not check["abstained"] else "ask_patient")
                )
                # next_tools is deliberately not executed or copied into a tool registry.
                return ImageRoute(
                    image_type=image_type,
                    checked=check["checked"],
                    abstained=check["abstained"],
                    suggested_workflow=workflow,
                    message=payload["message"][:500],
                )
        except VisionSchemaError:
            raise ValidationError("Image routing could not validate this photo") from None
        except VisionError:
            from ..domain.errors import ProviderUnavailableError

            raise ProviderUnavailableError("Photo routing unavailable; choose the source type yourself") from None

    def extract_medication_source(
        self,
        *,
        source_document_id: UUID,
        source_kind: Literal["package", "pharmacy_label", "prescription"],
        image_bytes: bytes,
        medications: tuple[ListedMedication, ...] = (),
    ) -> MedicationSourceExtractionDTO:
        try:
            clean = sanitize_image(image_bytes)
        except VisionSchemaError:
            raise ValidationError("Invalid or unsafe PNG/JPEG image") from None
        try:
            with self._factory() as client:
                transport = HttpxStage2Transport(
                    client=client,
                    contract=self._contract,
                    base_url=self._base_url,
                    get_retries=0,
                    sleep=lambda _seconds: None,
                )
                return PharmaScanLabelProvider(transport=transport, contract=self._contract).extract_medication_source(
                    source_document_id=source_document_id,
                    source_kind=source_kind,
                    image_bytes=clean,
                    medications=medications,
                )
        except VisionRequestError as exc:
            if exc.status_code in {401, 409, 429}:
                raise ProviderUnavailableError(
                    "Label service is unavailable or incompatible; try again later"
                ) from None
            raise ValidationError("Stage2 rejected this source image; use manual enrollment") from None
        except VisionError:
            raise ProviderUnavailableError(
                "Label extraction unavailable or unsupported; use manual enrollment"
            ) from None
