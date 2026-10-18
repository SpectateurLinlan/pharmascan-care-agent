"""DEMO_ONLY actual FastAPI read path; no external credentials/providers or production writes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from uuid import UUID

from app.contracts.dose_display import DoseBasis  # noqa: E402
from app.contracts.dto import SourceDocumentDTO  # noqa: E402
from app.transport.auth import AuthBoundary, StaticTokenVerifier  # noqa: E402

from .records_browser_server import NOW, OWNER, build_records_app, fixture_id


def build_grouped_records_app():
    app = build_records_app()
    app.state.container.auth = AuthBoundary(
        mode="supabase",
        verifier=StaticTokenVerifier(
            {
                "DEMO.synthetic-session-token": {"sub": str(OWNER)},
                "DEMO.confirmation-session-token": {"sub": str(UUID(int=424242))},
            }
        ),
    )
    store = app.state.container.store
    for number, name, strength in [
        (1, "Amlodipine", "5 mg"),
        (2, "Amlodipine", "10 mg"),
        (3, "Metformin", "500 mg"),
        (4, "Metformin", "500 mg"),
    ]:
        identity, source_id = fixture_id(100 + number), fixture_id(500 + number)
        row = store.medications[(OWNER, identity)]
        store.medications[(OWNER, identity)] = row.model_copy(
            update={
                "display_name": "DEMO " + name,
                "source_id": source_id,
            }
        )
        store.sources[(OWNER, source_id)] = SourceDocumentDTO(
            id=source_id,
            patient_id=OWNER,
            source_kind="pharmacy_label",
            review_status="user_reviewed",
            reviewed_at=NOW,
            dose_basis=DoseBasis(strength_text=strength, form="tablet", patient_checked=True),
        )
        for key, plan in tuple(store.regimens.items()):
            if key[0] == OWNER and plan.patient_medication_id == identity:
                store.regimens[key] = plan.model_copy(update={"source_id": source_id})
    for number, prior in [(2, 1), (3, 2)]:
        key = (OWNER, fixture_id(number))
        store.regimens[key] = store.regimens[key].model_copy(update={"supersedes_id": fixture_id(prior)})
    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(build_grouped_records_app(), host="127.0.0.1", port=8768, log_level="warning")
