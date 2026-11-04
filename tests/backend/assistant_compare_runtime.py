"""Explicit loopback DEMO visual evidence replay; no real Stage2/model/notification calls."""

from io import BytesIO

from app.application.visual_check import VisualCheckService
from app.contracts.vision import PillCandidate, ScanDiagnostics
from app.contracts.visual_check import VisualEvidence
from app.domain.errors import ProviderUnavailableError
from PIL import Image

from .assistant_knowledge_runtime import create_app as knowledge_app
from .test_medication_evidence import Vision


class DemoVisualReplay:
    def inspect(self, data):
        with Image.open(BytesIO(data)) as image:
            eligible = image.size == (96, 96) and image.convert("RGB").getpixel((10, 10)) == (0, 120, 70)
        if not eligible:
            raise ProviderUnavailableError("No synthetic catalogue evidence for this DEMO image")
        return VisualEvidence(model=Vision.model, detection=ScanDiagnostics(pill_count=1), candidates=[
            PillCandidate(external_catalogue_id="DEMO-public-catalogue", display_name="DEMO catalogue clue",
                          strength="DEMO 1 mg", visual_similarity=0.99),
        ])


class DemoEmptyReferences:
    def encode(self, image):
        raise AssertionError("DEMO has no eligible references; never encode an image")

    def compare(self, query, references, names):
        raise AssertionError("DEMO has no eligible references; never fabricate a match")


def create_app():
    return knowledge_app(workflows_enabled=True, workflow_visual=VisualCheckService(provider=DemoVisualReplay()),
                         workflow_personal_vision=DemoEmptyReferences())
