"""Synthetic HTTP gallery evidence-only acceptance; no Stage2 requests are made.

python -m tests.backend.accept_release_gallery --run-live
The ellipse is a DEMO reference, never evidence of actual medication identity.
"""

import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.application.personal_gallery import PersonalGalleryService  # noqa: E402
from app.application.timezone import PreferenceTzProvider  # noqa: E402
from app.infrastructure.evidence_images import patient_reference_image  # noqa: E402
from app.infrastructure.evidence_repos import MemoryEvidenceRepository, MemoryImageStore  # noqa: E402
from app.infrastructure.memory_repos import InMemoryPatientMedicationRepository  # noqa: E402

from .correctness02_support import TOKEN, build_harness  # noqa: E402


def run():
    output = ROOT / "outputs/release/multimodal/gallery.json"
    result = {
        "mode": "Synthetic HTTP/gallery evidence-only; local memory Storage; no Stage2 calls",
        "cases": [],
        "clinical_identity_verified": False,
    }
    h = build_harness()
    try:

        class NoComparisonVision:
            def encode(self, _image):
                raise AssertionError("Evidence-only upload must not request an embedding")

            def compare(self, *_args):
                raise AssertionError("Evidence-only photos must not enter matching")

        h.root.gallery = PersonalGalleryService(
            repository=MemoryEvidenceRepository(InMemoryPatientMedicationRepository(h.root.store)),
            storage=MemoryImageStore(),
            vision=NoComparisonVision(),
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
            uploaded_body = uploaded.json()
            image_id = uploaded_body["photo"]["id"]
            repeated = h.client.post(
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
            result["cases"].append(
                {"case": "duplicate_upload", "http": repeated.status_code, "actual": repeated.json()}
            )
            checked = h.client.post("/api/evidence/check-dose", headers=headers, content=data)
            result["cases"].append(
                {
                    "case": "comparison_fails_closed_without_validated_content_classifier",
                    "http": checked.status_code,
                    "actual": checked.json(),
                }
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
