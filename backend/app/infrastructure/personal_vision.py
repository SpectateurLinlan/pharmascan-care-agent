"""Injected versioned contracts with independent embedding compatibility checks."""

from collections import defaultdict

import httpx

from ..contracts.medication_evidence import ImageEmbedding
from ..contracts.vision import EmbeddingResult, GalleryReference, MatchOutcome, ModelMetadata, VisionError
from ..domain.errors import ProviderUnavailableError
from .stage2_adapter import HttpStage2VisionProvider, project
from .stage2_http import HttpxStage2Transport
from .stage2_schema import Stage2Contract
from .stage2_wire import ModelInfoWire


class PersonalVisionGateway:
    def __init__(self, *, base_url: str, contract: Stage2Contract, client_factory=httpx.Client):
        self._url, self._contract, self._factory = base_url, contract, client_factory

    def _provider(self, client: httpx.Client) -> HttpStage2VisionProvider:
        transport = HttpxStage2Transport(
            client=client, contract=self._contract, base_url=self._url, get_retries=0, sleep=lambda _: None
        )
        wire = project(self._contract, "ModelInfo", transport.get_json("/v1/model-info"), ModelInfoWire)
        return HttpStage2VisionProvider(
            transport=transport,
            contract=self._contract,
            embedding_space_id=wire.embedding_space_id,
            model_version=wire.model_version,
            preprocessing_version=wire.preprocess_version,
        )

    def encode(self, image: bytes) -> tuple[ModelMetadata, EmbeddingResult]:
        try:
            with self._factory() as client:
                provider = self._provider(client)
                # Real schema audit: Embedding/MatchRequest/MatchResponse are
                # unchanged; nested match types add optional reference_set_id.
                # Frozen validators and metadata/norm checks still apply.
                model = provider.model_info(read_only_v09_compatibility=True)
                return model, provider.embed(image_bytes=image, modality="loose_pill")
        except VisionError:
            raise ProviderUnavailableError("Personal photo embedding unavailable or incompatible") from None

    def compare(self, query: EmbeddingResult, references: list[ImageEmbedding], names: dict[str, str]) -> MatchOutcome:
        grouped: dict[str, list[ImageEmbedding]] = defaultdict(list)
        for reference in references:
            grouped[str(reference.medication_id)].append(reference)
        gallery = [
            GalleryReference(
                medication_id=key,
                name=names[key],
                embeddings=[row.result.embedding for row in rows],
                embedding_space_id=rows[0].result.embedding_space_id,
                model_version=rows[0].result.model_version,
                preprocessing_version=rows[0].result.preprocessing_version,
            )
            for key, rows in grouped.items()
        ]
        try:
            with self._factory() as client:
                provider = self._provider(client)
                provider.model_info(read_only_v09_compatibility=True)
                return provider.match(queries=[query], gallery=gallery)
        except VisionError:
            raise ProviderUnavailableError("Personal comparison unavailable or incompatible") from None
