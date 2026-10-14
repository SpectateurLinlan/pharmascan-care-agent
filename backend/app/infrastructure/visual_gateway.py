"""Reuse v0.8 strict adapter, owned client and validated image processing."""

from collections.abc import Callable

import httpx

from ..contracts.vision import VisionError, VisionSchemaError
from ..contracts.visual_check import VisualEvidence
from ..domain.errors import ProviderUnavailableError, ValidationError
from .stage2_adapter import HttpStage2VisionProvider, project
from .stage2_http import HttpxStage2Transport, sanitize_image
from .stage2_schema import Stage2Contract
from .stage2_wire import ModelInfoWire


class VisualGateway:
    def __init__(
        self, *, base_url: str, contract: Stage2Contract, client_factory: Callable[[], httpx.Client] = httpx.Client
    ):
        self._url, self._contract, self._factory = base_url, contract, client_factory

    def inspect(self, image: bytes) -> VisualEvidence:
        try:
            clean = sanitize_image(image)
        except VisionSchemaError:
            raise ValidationError("Invalid or unsafe PNG/JPEG") from None
        try:
            with self._factory() as client:
                transport = HttpxStage2Transport(
                    client=client, contract=self._contract, base_url=self._url, get_retries=0, sleep=lambda _: None
                )
                declared = project(self._contract, "ModelInfo", transport.get_json("/v1/model-info"), ModelInfoWire)
                provider = HttpStage2VisionProvider(
                    transport=transport,
                    contract=self._contract,
                    embedding_space_id=declared.embedding_space_id,
                    model_version=declared.model_version,
                    preprocessing_version=declared.preprocess_version,
                )
                model = provider.model_info(read_only_v09_compatibility=True)
                detection = provider.detect(image_bytes=clean)
                candidates = (
                    [] if detection.input_abstained else provider.identify_candidates(image_bytes=clean, top_k=5)
                )
                return VisualEvidence(model=model, detection=detection, candidates=candidates)
        except VisionError:
            raise ProviderUnavailableError(
                "Photo evidence is unavailable. Review your recorded instructions."
            ) from None
