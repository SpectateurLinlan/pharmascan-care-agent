"""DEMO_ONLY combined actual App API: synthetic memory, no external services."""

from datetime import timedelta

from app.contracts.dto import RegimenDraftInput

from .correctness02_support import OWNER, build_harness


def build_app():
    h = build_harness()
    h.root.clock.advance(hours=-3)  # 09:00 Asia/Singapore
    for plan in h.plans[:3]:
        medication = h.root.enrollment.get_medication(OWNER, plan.medication.id)
        h.root.store.medications[(OWNER, medication.id)] = medication.model_copy(
            update={"display_name": "DEMO Amlodipine"}
        )
    for key, event in list(h.root.store.events.items()):
        h.root.store.events[key] = event.model_copy(update={"created_at": h.root.clock.now() - timedelta(minutes=30)})
    h.root.enrollment.end_regimen(patient_id=OWNER, regimen_id=h.plans[3].regimen.id)
    prn = h.root.enrollment.enroll_draft(
        patient_id=OWNER,
        draft=RegimenDraftInput(
            medication_name="DEMO as-needed medicine",
            dose_amount=1,
            dose_unit="tablet",
            is_prn=True,
            food_instruction="DEMO_ONLY reviewed guidance; only when instructed",
        ),
    )
    h.root.enrollment.review_source_fields(patient_id=OWNER, source_id=prn.regimen.source_id)
    session = h.root.orchestrator.start_session(patient_id=OWNER)
    session = h.root.orchestrator.await_confirmation(patient_id=OWNER, session_id=session.id)
    challenge, _ = h.root.enrollment.request_activation_challenge(
        patient_id=OWNER, regimen_id=prn.regimen.id, session_id=session.id, session_state_version=session.state_version
    )
    h.root.enrollment.confirm_challenge(patient_id=OWNER, challenge_id=challenge.id)
    h.root.enrollment.activate_regimen(
        patient_id=OWNER,
        regimen_id=prn.regimen.id,
        challenge_id=challenge.id,
        session_state="awaiting_confirmation",
        session_state_version=session.state_version,
    )

    @h.app.post("/api/demo-only/advance-clock")
    def advance_clock():
        h.root.clock.advance(hours=2)
        return {"demo_only": True, "as_of": h.root.clock.now(), "dose_event_count": len(h.root.store.events)}

    return h.app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(build_app(), host="127.0.0.1", port=8771, log_level="warning")
