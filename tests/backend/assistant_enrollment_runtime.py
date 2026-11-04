"""Explicit loopback DEMO label replay. Never a deployment entry point."""

from io import BytesIO

from app.application.source_preview import SourcePreviewService
from app.domain.errors import ProviderUnavailableError
from app.infrastructure.memory_repos import SequentialIdGenerator
from PIL import Image

from .assistant_knowledge_runtime import create_app as knowledge_app
from .test_workflow_photo_enrollment import label


class DemoLabelReplay:
    def extract_medication_source(self, *, source_document_id, source_kind, image_bytes, medications=()):
        with Image.open(BytesIO(image_bytes)) as image:
            eligible = image.size == (96, 96) and image.convert("RGB").getpixel((10, 10)) == (0, 120, 70)
        if not eligible:
            raise ProviderUnavailableError("No synthetic label replay for this DEMO image")
        return label().model_copy(update={"source_document_id": source_document_id, "source_kind": source_kind})


def create_app(*, clock=None):
    return knowledge_app(
        workflows_enabled=True,
        workflow_preview=SourcePreviewService(provider=DemoLabelReplay(), ids=SequentialIdGenerator()),
        clock=clock,
    )
