"""Bounded real Stage2 through actual FastAPI upload/application paths.

Synthetic generated images, explicit consent, local patient persistence only.
python -m tests.backend.accept_release_multimodal --run-live
"""

import argparse
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402
from app.application.source_preview import SourcePreviewService  # noqa: E402
from app.config import Settings  # noqa: E402
from app.infrastructure.source_gateway import SourceGateway  # noqa: E402
from app.infrastructure.stage2_schema import Stage2Contract  # noqa: E402
from app.transport.container import build_visual_check  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from scripts.stage2_v010_smoke import demo_image  # noqa: E402

from .correctness02_support import TOKEN, build_harness  # noqa: E402


def run(*, visual_only: bool = False):
    settings = Settings.from_env()
    folder = ROOT / "outputs/release/multimodal"
    folder.mkdir(parents=True, exist_ok=True)
    report = {
        "mode": "Real Stage2 + actual FastAPI/application; synthetic images/local memory; no live Storage",
        "cases": [],
    }
    try:
        with httpx.Client(timeout=30) as http:
            schema = http.get(settings.vision_api_base_url.rstrip("/") + "/openapi.json")
            schema.raise_for_status()
            spec = schema.json()
        contract = Stage2Contract(spec)
        report["api_version"] = spec.get("info", {}).get("version")
        h = build_harness()
        gateway = SourceGateway(base_url=settings.vision_api_base_url, contract=contract)
        h.root.source_preview = SourcePreviewService(provider=gateway, routing=gateway, ids=h.root.ids)
        h.root.visual_check = build_visual_check(settings=settings)
        labels = {
            "package": [
                "DEMO ONLY - SYNTHETIC MEDICINE BOX",
                "METFORMIN 500 mg",
                "EXTENDED RELEASE TABLETS",
                "30 tablets",
            ],
            "pharmacy_label": [
                "DEMO ONLY - SYNTHETIC PHARMACY LABEL",
                "METFORMIN 500 mg",
                "Take ONE tablet TWICE a day AFTER FOOD.",
                "For 7 days. Swallow whole.",
            ],
            "prescription": [
                "DEMO ONLY - SYNTHETIC PRESCRIPTION",
                "Metformin 500 mg tablets",
                "Take ONE tablet daily at 20:00 for 7 days.",
            ],
        }
        headers = {
            "Authorization": "Bearer " + TOKEN,
            "Content-Type": "image/png",
            "x-stage2-consent": "true",
            "x-demo-only": "true",
        }
        for kind, lines in ({} if visual_only else labels).items():
            image = demo_image(lines)
            (folder / (kind + ".png")).write_bytes(image)
            response = h.client.post(
                "/api/sources/preview", params={"source_kind": kind}, headers=headers, content=image
            )
            result = response.json()
            report["cases"].append(
                {
                    "case": kind,
                    "http": response.status_code,
                    "actual": result,
                    "ground_truth": lines,
                    "no_activation": len(h.root.store.events) == 3,
                }
            )
            print(json.dumps({"case": kind, "http": response.status_code}), flush=True)
        image = Image.new("RGB", (640, 480), "#536e80")
        ImageDraw.Draw(image).ellipse((240, 160, 400, 300), fill="white")
        data = io.BytesIO()
        image.save(data, format="PNG")
        content = data.getvalue()
        (folder / "unknown-synthetic-pill.png").write_bytes(content)
        paths = ["/api/visual-check"] if visual_only else ["/api/sources/check-input", "/api/visual-check"]
        for path in paths:
            response = h.client.post(path, headers=headers, content=content)
            report["cases"].append(
                {
                    "case": path,
                    "http": response.status_code,
                    "actual": response.json(),
                    "ground_truth": (
                        "Generated ellipse, no established medication "
                        "identity; must not confirm an identity or ingestion."
                    ),
                }
            )
            print(json.dumps({"case": path, "http": response.status_code}), flush=True)
        denied = h.client.post("/api/visual-check", headers={**headers, "x-stage2-consent": "false"}, content=content)
        report["consent_denial_http"] = denied.status_code
        report["dose_events_unchanged"] = len(h.root.store.events) == 3
    except Exception as error:
        report["blocked_error_type"] = type(error).__name__
    (folder / ("visual-final.json" if visual_only else "actual.json")).write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", required=True)
    parser.add_argument("--visual-only", action="store_true")
    args = parser.parse_args()
    run(visual_only=args.visual_only)
