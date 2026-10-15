"""Explicit, bounded REAL Stage2 probes using generated demo_only labels.

No feedback endpoint, voice, patient data or paid provisioning. Raw results stay
in ignored outputs/. Run with PYTHONPATH=backend after reviewing configured URL.
"""

import io
import json
from pathlib import Path
from uuid import uuid4

import httpx
from app.config import Settings
from app.infrastructure.stage2_http import HttpxStage2Transport
from app.infrastructure.stage2_label_adapter import PharmaScanLabelProvider
from app.infrastructure.stage2_schema import Stage2Contract
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def demo_image(lines: list[str]) -> bytes:
    image = Image.new("RGB", (1300, 850), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 38)
    for index, text in enumerate(lines):
        draw.text((45, 35 + index * 70), text, fill="black", font=font)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


if __name__ == "__main__":
    settings = Settings.from_env()
    contract = Stage2Contract(
        json.loads((ROOT / "docs/external/pharmascan-api-openapi-0.10.0.json").read_text(encoding="utf-8"))
    )
    folder = ROOT / "outputs/stage2-v010"
    folder.mkdir(parents=True, exist_ok=True)
    labels = {
        "package": ["DEMO ONLY - SYNTHETIC MEDICINE BOX", "METFORMIN 500 mg", "EXTENDED RELEASE TABLETS", "30 tablets"],
        "pharmacy_label": [
            "DEMO ONLY - SYNTHETIC PHARMACY LABEL",
            "DEMO Singapore Pharmacy",
            "METFORMIN 500 mg EXTENDED RELEASE",
            "Take ONE tablet TWICE a day AFTER FOOD.",
            "For 7 days. Swallow whole.",
            "Quantity: 14 tablets",
            "Dispensed: 15 Oct 2026",
            "Expiry: 15 Oct 2027",
        ],
    }
    failures = 0
    with httpx.Client() as client:
        transport = HttpxStage2Transport(
            client=client,
            contract=contract,
            base_url=settings.vision_api_base_url,
            timeout_seconds=90,
            get_retries=1,
            sleep=lambda seconds: None,
        )
        provider = PharmaScanLabelProvider(transport=transport, contract=contract)
        for kind, lines in labels.items():
            content = demo_image(lines)
            (folder / f"{kind}.png").write_bytes(content)
            try:
                result = provider.extract_medication_source(
                    source_document_id=uuid4(), source_kind=kind, image_bytes=content
                )
                (folder / f"{kind}-extraction.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
                print(kind, "SCHEMA VALID", result.label_kind, "candidates", len(result.candidates), flush=True)
                for candidate in result.candidates:
                    print(
                        candidate.product.name,
                        candidate.product.strength,
                        candidate.regimen_evidence.instructions.model_dump()
                        if candidate.regimen_evidence.instructions
                        else None,
                        flush=True,
                    )
            except Exception as exc:
                # Provider exceptions contain no credentials, but do not print raw bodies.
                failures += 1
                print(kind, "FAILED", type(exc).__name__, flush=True)

    raise SystemExit(1 if failures else 0)
