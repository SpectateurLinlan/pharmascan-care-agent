"""DEMO-only structural read regressions; never live Supabase timing evidence."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from app.application.timezone import FixedTzProvider
from app.contracts.dto import RegimenVersionDTO, SourceDocumentDTO
from app.domain.errors import AuthenticationRequiredError, NotFoundError, ProviderUnavailableError
from app.infrastructure.supabase_data import SupabaseDataClient
from app.infrastructure.supabase_repos import Regimens, Sources
from app.timing import RequestTiming, current_timing

from .correctness02_support import OWNER, build_harness
from .test_patient_app_repairs import PATIENT, activate, services


def test_gallery_and_review_reuse_owned_plan_and_source_batches():
    root = build_harness().root
    enrollment = root.enrollment
    with (
        patch.object(enrollment, "get_source", wraps=enrollment.get_source) as sources,
        patch.object(enrollment, "list_regimens", wraps=enrollment.list_regimens) as plans,
        patch.object(enrollment, "list_medications", wraps=enrollment.list_medications) as medications,
    ):
        assert root.gallery.list(OWNER)
        assert sources.call_count == plans.call_count == 0
        medications.reset_mock()
        report = root.long_term.review(OWNER, 30, "Asia/Singapore")
        assert report.source_records and report.summary.medications
        assert medications.call_count == 1
        assert sources.call_count == plans.call_count == 0
    context = enrollment.read_context(OWNER)
    with pytest.raises(NotFoundError):
        root.long_term.inventory(PATIENT, context.medications[0].id, context=context)


@pytest.mark.parametrize("zone,moment", [
    ("Asia/Singapore", datetime(2026, 10, 21, tzinfo=UTC)),
    ("America/New_York", datetime(2026, 3, 8, tzinfo=UTC)),
    ("America/New_York", datetime(2026, 11, 1, tzinfo=UTC)),
])
def test_batch_deadlines_match_fresh_individual_boundaries_and_read_each_plan_once(wired, zone, moment):
    wired.clock._moment = moment
    plan = activate(wired, 0)
    wired.schedule._tz = FixedTzProvider(zone)
    for key, rule in list(wired.store.dose_rules.items()):
        if rule.regimen_id == plan:
            wired.store.dose_rules[key] = rule.model_copy(update={
                "timezone": zone, "local_times": ["01:30", "03:30", "23:30"],
            })
    occurrences = wired.schedule.materialize(patient_id=PATIENT, regimen_id=plan, days=2)
    reminders, _ = services(wired)
    reminders._tz = FixedTzProvider(zone)
    expected = {row.id: reminders.deadline(PATIENT, row) for row in occurrences}
    with (
        patch.object(wired.regimens, "get", wraps=wired.regimens.get) as plans,
        patch.object(wired.dose_rules, "list_for_regimen", wraps=wired.dose_rules.list_for_regimen) as rules,
    ):
        assert reminders.deadlines(PATIENT, occurrences) == expected
        assert plans.call_count == rules.call_count == 1
    assert len(occurrences) > 1


def test_supabase_batches_keep_scoping_complete_counts_and_safe_operation_timings():
    root = build_harness().root
    source = next(iter(root.store.sources.values()))
    plan = next(iter(root.store.regimens.values()))
    requests = []
    broken = False

    def handle(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.params["patient_id"] == f"eq.{OWNER}"
        row = source if request.url.path.endswith("source_documents") else plan
        rows = [] if broken else [row.model_dump(mode="json")]
        return httpx.Response(200, json=rows, headers={"Content-Range": "*/1"})

    timing = RequestTiming()
    marker = current_timing.set(timing)
    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as http:
            client = SupabaseDataClient(
                base_url="https://synthetic.invalid", publishable_key="sb_publishable_DEMO",
                access_token="DEMO_PRIVATE", patient_id=OWNER, client=http,
            )
            sources = Sources(client, "source_documents", SourceDocumentDTO)
            plans = Regimens(client, "regimen_versions", RegimenVersionDTO)
            assert sources.get_many(OWNER, [source.id, source.id]) == [source]
            assert plans.list_for_medications(OWNER, [plan.patient_medication_id]) == [plan]
            assert len(requests) == 2
            plans.list_for_medications(OWNER, [plan.patient_medication_id], active_only=True)
            assert requests[-1].url.params["state"] == "eq.active"
            with pytest.raises(AuthenticationRequiredError):
                sources.get_many(PATIENT, [source.id])
            assert len(requests) == 3
            broken = True
            with pytest.raises(ProviderUnavailableError):
                sources.get_many(OWNER, [source.id])
        header = timing.header()
        assert "db_source_documents_read_batch" in header and "max_ms=" in header
        assert str(source.id) not in header and str(OWNER) not in header and "DEMO_PRIVATE" not in header
        assert timing.data_requests == 4
    finally:
        current_timing.reset(marker)


def test_followup_history_work_is_bounded_by_the_returned_page():
    root = build_harness().root
    service = root.late_reports
    with (
        patch.object(service.repository, "history", wraps=service.repository.history) as singles,
        patch.object(service.repository, "histories", wraps=service.repository.histories) as batches,
    ):
        result = service.recent(OWNER, include_reported=True)
        assert result["items"]
        assert singles.call_count == 0 and batches.call_count == 1
        assert len(batches.call_args.args[1]) <= 50
    with patch.object(service.repository, "histories", side_effect=ProviderUnavailableError("unavailable")):
        with pytest.raises(ProviderUnavailableError):
            service.recent(OWNER)


def test_followup_large_existing_history_reads_corrections_only_for_the_50_returned_rows():
    root = build_harness().root
    seed = next(row for row in root.store.occurrences.values() if row.patient_id == OWNER)
    for index in range(65):
        row = seed.model_copy(update={
            "id": uuid4(), "due_at": root.clock.now() - timedelta(hours=2, minutes=index),
            "generation_key": f"DEMO_ONLY_P0_{index}",
        })
        root.store.occurrences[OWNER, row.id] = row
    with patch.object(root.late_reports.repository, "histories", wraps=root.late_reports.repository.histories) as reads:
        result = root.late_reports.recent(OWNER, include_reported=True)
    assert result["has_more"] and len(result["items"]) == 50
    assert reads.call_count == 1 and len(reads.call_args.args[1]) == 50


def test_operation_labels_never_retain_private_path_or_filter_values():
    from app.timing import timed_data_operation

    timing = RequestTiming()
    marker = current_timing.set(timing)
    try:
        with timed_data_operation("/rest/v1/private-DEMO-secret", "GET", {"id": "eq.PRIVATE"}):
            pass
        assert "PRIVATE" not in timing.header() and "DEMO" not in timing.header()
        assert "db_other_read_one" in timing.header()
    finally:
        current_timing.reset(marker)


def test_today_projects_two_windows_with_one_plan_and_rule_read_and_batches_history_events():
    root = build_harness().root
    plan = next(row for row in root.store.regimens.values() if row.patient_id == OWNER and row.state.value == "active")
    now = root.clock.now()
    windows = [(now, now + timedelta(days=1)), (now, now + timedelta(days=2))]
    expected = [root.schedule.planned_instants(patient_id=OWNER, regimen_id=plan.id, start=start, end=end)
                for start, end in windows]
    with (
        patch.object(root.schedule._regimens, "get", wraps=root.schedule._regimens.get) as plans,
        patch.object(root.schedule._rules, "list_for_regimen", wraps=root.schedule._rules.list_for_regimen) as rules,
    ):
        assert root.schedule.planned_windows(patient_id=OWNER, regimen_id=plan.id, windows=windows) == expected
        assert plans.call_count == rules.call_count == 1
    with (
        patch.object(
            root.self_report._events, "find_by_occurrence", wraps=root.self_report._events.find_by_occurrence
        ) as single,
        patch.object(
            root.self_report._events, "list_for_patient", wraps=root.self_report._events.list_for_patient
        ) as window,
    ):
        root.self_report.history(patient_id=OWNER, regimen_id=plan.id,
                                 window_start=now - timedelta(days=7), window_end=now)
        assert single.call_count == window.call_count == 0


@pytest.mark.parametrize("attention_only", [True, False])
@pytest.mark.parametrize("disable_rule", [True, False])
def test_combined_due_read_matches_existing_selection_and_reuses_owned_window(wired, attention_only, disable_rule):
    plan = activate(wired, 0)
    wired.schedule.materialize(patient_id=PATIENT, regimen_id=plan, days=2)
    if disable_rule:
        for key, rule in list(wired.store.dose_rules.items()):
            if rule.regimen_id == plan:
                wired.store.dose_rules[key] = rule.model_copy(update={"enabled": False})
    # Persisted occurrences remain visible even when their rule is disabled.
    expected = wired.schedule.find_due(patient_id=PATIENT, regimen_id=plan, attention_only=attention_only)
    with (
        patch.object(wired.regimens, "get", wraps=wired.regimens.get) as plans,
        patch.object(wired.occurrences, "list_for_regimen", wraps=wired.occurrences.list_for_regimen) as windows,
    ):
        regimen, actual = wired.schedule.read_due(
            patient_id=PATIENT, regimen_id=plan, attention_only=attention_only
        )
        assert regimen.id == plan and actual == expected
        assert plans.call_count == 1
        assert windows.call_count == (1 if attention_only else 2)


def test_attention_owned_read_interfaces_match_fresh_reads_and_reject_foreign_context():
    from app.application.today_attention import read_today_attention
    from app.domain.errors import ValidationError

    root = build_harness().root
    context = root.enrollment.read_context(OWNER)
    plan = next(row for row in context.regimens if row.state.value == "active")
    medicine = next(row for row in context.medications if row.id == plan.patient_medication_id)
    now = root.clock.now()
    expected = root.self_report.history(
        patient_id=OWNER, regimen_id=plan.id, window_start=now - timedelta(days=7), window_end=now
    )
    assert root.self_report.history_for_plan(
        patient_id=OWNER, regimen=plan, medication=medicine,
        window_start=now - timedelta(days=7), window_end=now,
    ) == expected
    with pytest.raises(ValidationError):
        root.self_report.history_for_plan(
            patient_id=PATIENT, regimen=plan, medication=medicine, window_start=now, window_end=now
        )
    with (
        patch.object(root.self_report._regimens, "get", wraps=root.self_report._regimens.get) as plans,
        patch.object(root.self_report._medications, "get", wraps=root.self_report._medications.get) as medicines,
    ):
        result = read_today_attention(owner=OWNER, enrollment=root.enrollment, schedule=root.schedule,
                                      reports=root.self_report, clock=root.clock)
        assert result.plans and plans.call_count == medicines.call_count == 0


def test_combined_due_first_load_uses_the_canonical_id_after_an_insert_race(wired):
    plan = activate(wired, 0)
    winner = uuid4()
    original = wired.occurrences.add

    def concurrent_add(row):
        original(row.model_copy(update={"id": winner}) if row.due_at == wired.clock.now() else row)

    with patch.object(wired.occurrences, "add", side_effect=concurrent_add):
        _, due = wired.schedule.read_due(patient_id=PATIENT, regimen_id=plan, attention_only=True)
    assert due.occurrence is not None and due.occurrence.id == winner
