"""Local synthetic FastAPI for real React/browser workflows; no external sends."""

from datetime import timedelta
from uuid import uuid4

from app.contracts.long_term import CareTaskInput, TaskUpdate

from .correctness02_support import OWNER, build_harness


def build_app(no_active=False, multiple=False):
    h = build_harness()
    h.app.state.multiple_care_reminders_enabled = multiple
    h.root.clock.advance(days=1)
    care = h.root.long_term
    now = h.root.clock.now()
    for title, due in [
        ("DEMO prepare review", now + timedelta(days=2)),
        ("DEMO check collection", now - timedelta(days=1)),
    ]:
        care.create_task(
            OWNER,
            CareTaskInput(
                id=uuid4(),
                category="medication_review",
                title=title,
                due_at=due,
                reminder_minutes=None if due < now else 60,
                historical_confirmed=due < now,
                confirmed=True,
            ),
        )
    done = care.create_task(
        OWNER,
        CareTaskInput(
            id=uuid4(),
            category="refill",
            title="DEMO completed task",
            due_at=now + timedelta(days=1),
            reminder_minutes=None,
            confirmed=True,
        ),
    )
    care.update_task(OWNER, done.id, TaskUpdate(id=uuid4(), expected_version=1, status="completed", confirmed=True))
    if no_active:
        for medicine in h.root.enrollment.list_medications(OWNER):
            for plan in h.root.enrollment.list_regimens(OWNER, medicine.id):
                if plan.state.value == "active":
                    h.root.enrollment.end_regimen(patient_id=OWNER, regimen_id=plan.id)
    return h.app


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(
        build_app(
            no_active=os.environ.get("TODAY_CARE_NO_ACTIVE") == "1",
            multiple=os.environ.get("TODAY_CARE_MULTIPLE") == "1",
        ),
        host="127.0.0.1",
        port=8791,
        log_level="warning",
    )
