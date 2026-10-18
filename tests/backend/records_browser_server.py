"""DEMO_ONLY localhost browser harness: real FastAPI/routes/services, memory persistence.

No environment credentials, external providers, production SQL or patient writes.
Run explicitly: python -m tests.backend.records_browser_server
Synthetic fixtures are seeded directly; this is NOT historical backfill support.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.contracts.dto import DoseEventDTO, DoseOccurrenceDTO, PatientMedicationDTO, RegimenVersionDTO  # noqa: E402
from app.contracts.enums import IntakeStatus, OccurrenceStatus, RegimenState  # noqa: E402
from app.transport.app_factory import create_app  # noqa: E402
from app.transport.auth import AuthBoundary, StaticTokenVerifier  # noqa: E402
from app.transport.container import build_container  # noqa: E402

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)
OWNER = UUID("d00d0000-0000-4000-8000-000000000001")
TOKEN = "DEMO.synthetic-session-token"


class FixtureClock:
    def now(self) -> datetime:
        return NOW


class FixtureIds:
    def new_id(self) -> UUID:
        return uuid4()


def fixture_id(number: int) -> UUID:
    return UUID(f"de000000-0000-4000-8000-{number:012d}")


def build_records_app():
    container = build_container(
        clock=FixtureClock(),
        ids=FixtureIds(),
        auth=AuthBoundary(mode="supabase", verifier=StaticTokenVerifier({TOKEN: {"sub": str(OWNER)}})),
    )
    store = container.store
    assert store is not None
    # Deliberately reverse creation versus effective-date ordering. All data synthetic.
    definitions = [
        (1, 1, "A", 46, 32, 20),
        (2, 1, "A", 16, 6, 6),
        (3, 1, "A", 1, None, 20),
        (4, 2, "B", 4, None, 1),
        (5, 3, "C", 4, None, 0),
        (6, 4, "D", 4, None, 5),
        (7, 5, "E", 4, None, 6),
    ]
    for plan_number, medicine_number, name, age, ended, count in definitions:
        medication_id, regimen_id = fixture_id(100 + medicine_number), fixture_id(plan_number)
        store.medications[(OWNER, medication_id)] = PatientMedicationDTO(
            id=medication_id, patient_id=OWNER, display_name=f"DEMO medicine {name}", demo_only=True
        )
        store.regimens[(OWNER, regimen_id)] = RegimenVersionDTO(
            id=regimen_id,
            patient_id=OWNER,
            patient_medication_id=medication_id,
            source_id=None,
            version_no=100 - plan_number,
            state=RegimenState.ENDED if ended else RegimenState.ACTIVE,
            dose_amount=1,
            dose_unit="tablet",
            frequency_rule=None,
            is_prn=False,
            route="oral",
            food_instruction=None,
            effective_from=NOW - timedelta(days=age),
            effective_to=NOW - timedelta(days=ended) if ended else None,
            supersedes_id=None,
            confirmation_challenge_id=None,
            created_at=NOW - timedelta(minutes=plan_number),
            demo_only=True,
        )
        event_base = NOW - timedelta(days=40 if plan_number == 1 else 10 if plan_number == 2 else 1)
        if plan_number == 3:
            event_base += timedelta(hours=4, minutes=-1)  # 23:59 SG through next local day.
        for i in range(count):
            due = event_base + timedelta(minutes=i)
            occurrence_id = fixture_id(1000 + plan_number * 100 + i)
            store.occurrences[(OWNER, occurrence_id)] = DoseOccurrenceDTO(
                id=occurrence_id,
                patient_id=OWNER,
                regimen_id=regimen_id,
                rule_id=fixture_id(900),
                due_at=due,
                status=OccurrenceStatus.PAST_DUE,
                generation_key=f"demo_only:{occurrence_id}",
            )
            if i % 4 != 3:
                event_id = fixture_id(10000 + plan_number * 100 + i)
                store.events[(OWNER, event_id)] = DoseEventDTO(
                    id=event_id,
                    patient_id=OWNER,
                    regimen_id=regimen_id,
                    occurrence_id=occurrence_id,
                    event_time=due + timedelta(minutes=2),
                    intake_status=[IntakeStatus.REPORTED_TAKEN, IntakeStatus.REPORTED_NOT_TAKEN, IntakeStatus.UNSURE][
                        i % 4
                    ],
                    # Submission order intentionally opposes scheduled chronology.
                    created_at=NOW - timedelta(seconds=i),
                    idempotency_key=f"demo_only:{event_id}",
                )
        if plan_number == 3:
            occurrence_id = fixture_id(9999)
            store.occurrences[(OWNER, occurrence_id)] = DoseOccurrenceDTO(
                id=occurrence_id,
                patient_id=OWNER,
                regimen_id=regimen_id,
                rule_id=fixture_id(900),
                due_at=NOW + timedelta(hours=1),
                status=OccurrenceStatus.SCHEDULED,
                generation_key="demo_only:future",
            )
    return create_app(container)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(build_records_app(), host="127.0.0.1", port=8766, log_level="warning")
