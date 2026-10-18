"""Actual embed/match through personal gallery HTTP, synthetic reference/local Storage.

python -m tests.backend.accept_release_gallery --run-live
The ellipse is a DEMO reference, never evidence of actual medication identity.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402
from app.application.personal_gallery import PersonalGalleryService  # noqa: E402
from app.application.timezone import PreferenceTzProvider  # noqa: E402
from app.config import Settings  # noqa: E402
from app.infrastructure.evidence_images import patient_reference_image  # noqa: E402
from app.infrastructure.evidence_repos import MemoryEvidenceRepository, MemoryImageStore  # noqa: E402
from app.infrastructure.memory_repos import InMemoryPatientMedicationRepository  # noqa: E402
from app.infrastructure.personal_vision import PersonalVisionGateway  # noqa: E402
from app.infrastructure.stage2_schema import Stage2Contract  # noqa: E402

from .correctness02_support import TOKEN, build_harness  # noqa: E402


def run():
    settings = Settings.from_env()
    output = ROOT / "outputs/release/multimodal/gallery.json"
    result = {
        "mode": "Real Stage2 embed/match + actual HTTP/gallery; synthetic ellipse, local memory private Storage",
        "cases": [],
        "clinical_identity_verified": False,
    }
    h = build_harness()
    try:
        with httpx.Client(timeout=25) as client:
            response = client.get(settings.vision_api_base_url.rstrip("/") + "/openapi.json")
            response.raise_for_status()
            contract = Stage2Contract(response.json())
        h.root.gallery = PersonalGalleryService(
            repository=MemoryEvidenceRepository(InMemoryPatientMedicationRepository(h.root.store)),
            storage=MemoryImageStore(),
            vision=PersonalVisionGateway(base_url=settings.vision_api_base_url, contract=contract),
            enrollment=h.root.enrollment,
            normalize=patient_reference_image,
            clock=h.root.clock,
            ids=h.root.ids,
            tz_provider=PreferenceTzProvider(h.root.preferences),
        )
        data = (output.parent / "unknown-synthetic-pill.png").read_bytes()
        headers = {
            "Authorization": "Bearer " + TOKEN,
            "Content-Type": "image/png",
            "x-stage2-consent": "true",
            "x-demo-only": "true",
        }
        medication = h.plans[1].medication.id
        uploaded = h.client.post(
            f"/api/evidence/gallery/{medication}/images",
            headers=headers,
            content=data,
            params={
                "image_kind": "loose_pill",
                "source_description": "DEMO synthetic ellipse, not actual medicine identity",
                "reviewed": "true",
                "for_comparison": "true",
            },
        )
        result["cases"].append({"case": "upload_reference", "http": uploaded.status_code, "actual": uploaded.json()})
        print("upload_reference", uploaded.status_code, flush=True)
        if uploaded.status_code == 200:
            image_id = uploaded.json()["id"]
            checked = h.client.post("/api/evidence/check-dose", headers=headers, content=data)
            result["cases"].append(
                {"case": "self_visual_comparison", "http": checked.status_code, "actual": checked.json()}
            )
            foreign = h.client.get("/api/evidence/images/" + image_id, headers={"Authorization": "Bearer DEMO.foreign"})
            result["foreign_read_http"] = foreign.status_code
            retired = h.client.post("/api/evidence/images/" + image_id + "/retire", headers=headers)
            after = h.client.post("/api/evidence/check-dose", headers=headers, content=data)
            result["cases"] += [
                {"case": "retire", "http": retired.status_code, "actual": retired.json()},
                {"case": "check_after_retire", "http": after.status_code, "actual": after.json()},
            ]
        result["dose_events_unchanged"] = len(h.root.store.events) == 3
    except (httpx.HTTPError, ValueError, KeyError) as error:
        result["blocked_error_type"] = type(error).__name__
    finally:
        h.close()
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", required=True)
    parser.parse_args()
    run()
