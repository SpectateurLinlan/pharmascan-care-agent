"""Offline fixture executor; only explicit memory services and replay transports."""

import json
from contextlib import contextmanager
from datetime import timedelta
from time import perf_counter
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from app.application.medication_names import MedicationNameResolver
from app.application.medication_understanding import MedicationUnderstandingService
from app.application.workflow_knowledge import WorkflowKnowledgeService
from app.infrastructure.openfda_knowledge import OpenFDAKnowledge

from .assistant_eval import FIXTURE_IDS, ROOT, EvalCase, ObservedRun
from .test_workflow_originals import original_png
from .workflow_support import WorkflowHarness


class OfflineNetworkDenied(RuntimeError):
    pass


@contextmanager
def offline_network_guard():
    def deny(*args, **kwargs):
        raise OfflineNetworkDenied("Live transport is unavailable in offline evaluation")

    with (
        patch.object(httpx.HTTPTransport, "handle_request", deny),
        patch.object(httpx.AsyncHTTPTransport, "handle_async_request", deny),
        patch("socket.create_connection", deny),
        patch("urllib.request.urlopen", deny),
    ):
        yield


def clinical(snapshot):
    return {key: snapshot[key] for key in ("medications", "regimens", "dose_events", "sources", "source_fields")}


def binding(task, confirmed=True):
    return {
        "X-Assistant-Task": task["task_id"],
        "X-Assistant-Revision": str(task["revision"]),
        "X-Patient-Confirmed": str(confirmed).lower(),
    }


def message(h, text, language, view=None):
    payload = {"text": text, "language": language, "workspace_id": h.workspace_id, "client_turn_id": str(uuid4())}
    if view:
        payload.update(task_id=view["task_id"], expected_revision=view["revision"])
    return h._request("POST", "/api/agent/workflows/messages", json=payload)["workflow"]


def prepare(h, capability, fields):
    task = h.start(capability, fields)
    return h.event(task["task_id"], "prepare_confirmation")


def facts_for_knowledge(result):
    knowledge = result["general_knowledge"]
    return {
        "knowledge_status": knowledge["status"],
        "has_sources": bool(knowledge["sources"]),
        "has_knowledge": knowledge["status"] == "matched" and bool(knowledge["use_facts"]),
        "knowledge_coverage": knowledge["coverage"],
        "personal_dosing_authority": knowledge["personal_dosing_authority"],
    }


def setup_knowledge(h, fixture):
    public = json.loads((ROOT / "tests/backend/fixtures/ibuprofen_labels_public.json").read_text(encoding="utf-8"))

    def replay(request):
        h.knowledge_requests.append(request)
        if fixture == "knowledge_timeout":
            raise httpx.ReadTimeout("DEMO synthetic timeout")
        if fixture == "knowledge_not_found":
            return httpx.Response(404)
        return httpx.Response(200, content=public["raw_response_utf8"], headers={"Content-Type": "application/json"})

    h.knowledge_http.close()
    h.knowledge_http = httpx.Client(transport=httpx.MockTransport(replay))
    resolver = MedicationNameResolver()
    understanding = MedicationUnderstandingService(
        h.container.enrollment,
        OpenFDAKnowledge(h.knowledge_http, h.clock, monotonic=lambda: 0, scoped_facts=True),
        h.clock,
        name_resolver=resolver,
    )
    h.container.medication_understanding = understanding
    h.container.assistant_knowledge = WorkflowKnowledgeService(
        workflows=h.container.assistant_workflows, understanding=understanding, resolver=resolver
    )


def execute(case, h):
    """Return observed structured data. Expected facts are deliberately never read."""
    fixture = case.setup_fixture
    evidence = [{"phase": "prepare", "source": "application"}]
    common = {
        "environment": "local_memory",
        "effects": {},
        "explanations": [],
        "evidence": evidence,
        "task_complete": False,
        "receipt_count": 0,
        "facts": {},
    }
    if fixture == "capability_prepare":
        catalog = h._request("GET", "/api/agent/workflows/capabilities")
        row = next(row for row in catalog["capabilities"] if row["id"] == case.capability_id)
        if not row["available"]:
            return {**common, "available": False, "unavailable_reason": row["reason"]}
        task = h.start(case.capability_id)
        common["facts"] = {"capability_id": task["capability_id"], "business_result": task["result_ref"] is not None}
    elif fixture == "manual_enrollment":
        task = None
        for text in case.turns:
            task = message(h, text, case.language, task)
        visible = task["visible_fields"]
        common["facts"] = {
            "method": visible.get("method"),
            "has_name": bool(visible.get("medication_name")),
            "ready_for_review": task["state"] == "ready_for_review",
            "active_regimens": sum(row["state"] == "active" for row in h.snapshot()["regimens"]),
        }
    elif fixture == "native_enrollment":
        task = prepare(
            h,
            "medication.enroll",
            {
                "method": "manual",
                "medication_name": "DEMO evaluation native medicine",
                "dose_amount": 1,
                "dose_unit": "tablet",
                "frequency_rule": {"kind": "daily", "local_times": ["08:00"]},
            },
        )
        regimen_id = task["result_ref"]["id"]
        draft = h._request("GET", f"/api/medications/drafts/{regimen_id}")
        h._request("POST", f"/api/medications/drafts/{draft['source_id']}/review", json={"field_ids": None})
        session = h._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})
        challenge = h._request(
            "POST",
            f"/api/medications/drafts/{regimen_id}/challenge",
            params={"session_id": session["session_id"]},
            json={},
            headers=binding(task),
        )
        h._request(
            "POST",
            "/api/medications/activate",
            headers=binding(task),
            json={
                "regimen_id": regimen_id,
                **{
                    key: challenge[key]
                    for key in ("challenge_id", "session_id", "session_state", "session_state_version")
                },
            },
        )
        done = h.event(task["task_id"], "report_business_result")
        plan = h.container.enrollment.get_regimen(h.owner_ids["A"], UUID(regimen_id))
        regimens = h.container.enrollment.list_regimens(h.owner_ids["A"], plan.patient_medication_id)
        active = sum(row.state == "active" for row in regimens)
        common.update(
            task_complete=done["state"] == "completed",
            receipt_count=int(done["state"] == "completed" and active == 1),
            facts={"saved": done["state"] == "completed", "active_regimens": active, "one_regimen": len(regimens) == 1},
        )
        evidence.extend(
            [
                {"phase": "patient_confirmation", "source": "native_api", "independently_confirmed": True},
                {"phase": "readback", "source": "owned_readback"},
            ]
        )
    elif fixture.startswith("knowledge_") or fixture == "name_confirmation":
        setup_knowledge(h, fixture)
        task = h.start("medication.knowledge", {"medication_name": case.turns[0]})
        payload = {"expected_revision": task["revision"]}
        before_choice = len(h.knowledge_requests)
        if fixture == "name_confirmation":
            response = h.client.post(
                f"/api/agent/workflows/tasks/{task['task_id']}/knowledge",
                params={"client_id": "DEMO-workflow-A"},
                json=payload,
            )
            common["facts"].update(
                asked_confirmation=response.status_code == 422,
                no_lookup_before_choice=len(h.knowledge_requests) == before_choice,
            )
            payload["candidate_id"] = task["visible_fields"]["name_resolution"]["candidates"][0]["id"]
        result = h._request("POST", f"/api/agent/workflows/tasks/{task['task_id']}/knowledge", json=payload)
        common["facts"].update(facts_for_knowledge(result))
        common["explanations"] = [row["operation_key"] + ":" + row["outcome"] for row in result["explanations"]]
        evidence.append({"phase": "read", "source": "application"})
        common["execution_mode"] = "replay"
        if result["general_knowledge"]["coverage"] == "partial":
            common["limitations"] = ("source_coverage_partial",)
        if fixture in {"knowledge_not_found", "knowledge_timeout"}:
            common.update(execution_mode="degraded", tool_errors=("public_source_unavailable",))
    elif fixture == "photo_failure":
        original = original_png()
        task = h.start("medication.enroll", {"method": "photo"})
        uploaded = h.upload(task["task_id"], original)
        retained = h.read_original(uploaded["attachment"]["id"]) == original
        common.update(
            execution_mode="degraded",
            tool_errors=("source_provider_unavailable",),
            facts={
                "original_retained": retained,
                "recoverable": uploaded["workflow"]["state"] == "failed_recoverable",
                "no_medication": not h.snapshot()["medications"],
            },
        )
    elif fixture == "no_save":
        h._request("PUT", "/api/me/preferences", json={"conversation_history_enabled": True})
        marker = "DEMO page-only evaluation medication"
        h.start("medication.enroll", {"method": "manual", "medication_name": marker}, save=False)
        state = h.snapshot()
        common["facts"] = {
            "no_saved_task": not state["tasks"],
            "no_saved_original": not state["originals"],
            "no_history": not state["history"],
            "no_body_in_controls": marker not in json.dumps(state["workflow_controls"]),
        }
        if not all(common["facts"].values()):
            common["effects"]["saved_content_without_consent"] = 1
    elif fixture in {"native_feedback", "stale_action"}:
        task = prepare(h, "feedback.submit", {"category": "issue", "message": "DEMO deterministic evaluation feedback"})
        payload = task["visible_fields"]["settings_review"]["payload"]
        target = UUID(payload["id"])
        if fixture == "stale_action":
            h.event(task["task_id"], "pause")
            response = h.client.post(
                "/api/feedback", params={"client_id": "DEMO-workflow-A"}, json=payload, headers=binding(task)
            )
            common["facts"] = {
                "stale_refused": response.status_code == 409,
                "nothing_saved": h.container.feedback.get(h.owner_ids["A"], target) is None,
            }
            evidence.append({"phase": "patient_action", "source": "native_api"})
        else:
            h.client.post(
                "/api/feedback", params={"client_id": "DEMO-workflow-A"}, json=payload, headers=binding(task, False)
            )
            common["effects"]["writes_without_confirmation"] = int(
                h.container.feedback.get(h.owner_ids["A"], target) is not None
            )
            first = h._request("POST", "/api/feedback", json=payload, headers=binding(task))
            replay = h._request("POST", "/api/feedback", json=payload, headers=binding(task))
            row = h.container.feedback.get(h.owner_ids["A"], target)
            done = h.event(task["task_id"], "report_business_result")
            matches = row is not None and row.message == payload["message"] and row.category == payload["category"]
            common.update(
                task_complete=done["state"] == "completed",
                receipt_count=int(matches and done["state"] == "completed"),
                facts={
                    "saved": row is not None,
                    "replayed_same_receipt": replay == first,
                    "native_record_matches": matches,
                },
            )
            evidence.extend(
                [
                    {"phase": "patient_confirmation", "source": "native_api", "independently_confirmed": True},
                    {"phase": "readback", "source": "owned_readback"},
                ]
            )
    elif fixture == "native_contact":
        task = prepare(
            h,
            "caregiver.add",
            {
                "name": "DEMO consenting evaluation contact",
                "relationship": "family",
                "contact_type": "email",
                "contact_value": "DEMO-eval@example.invalid",
                "storage_consent": True,
            },
        )
        payload = task["visible_fields"]["settings_review"]["payload"]
        h._request("POST", "/api/me/caregivers", json=payload, headers=binding(task))
        done = h.event(task["task_id"], "report_business_result")
        rows = h.container.caregivers.list(h.owner_ids["A"])
        common.update(
            task_complete=done["state"] == "completed",
            receipt_count=int(len(rows) == 1 and done["state"] == "completed"),
            facts={
                "saved": bool(rows),
                "one_contact": len(rows) == 1,
                "sharing_disabled": bool(rows) and not rows[0].sharing_enabled and not rows[0].notifications_enabled,
            },
        )
        evidence.extend(
            [
                {"phase": "patient_confirmation", "source": "native_api", "independently_confirmed": True},
                {"phase": "readback", "source": "owned_readback"},
            ]
        )
    elif fixture == "native_observation":
        task = prepare(
            h,
            "observation.add",
            {"description": "DEMO evaluation patient note", "occurred_at": h.clock.now().isoformat()},
        )
        payload = task["visible_fields"]["care_review"]["payload"]
        h._request("PUT", "/api/me/health-observations", json={**payload, "confirmed": True}, headers=binding(task))
        done = h.event(task["task_id"], "report_business_result")
        row = h.container.observations.get(h.owner_ids["A"], UUID(payload["id"]))
        matches = row is not None and row.description == payload["description"]
        count = len(h.container.observations.list(h.owner_ids["A"], h.clock.now() - timedelta(days=1), h.clock.now()))
        common["effects"]["clinical_writes"] = count
        common.update(
            task_complete=done["state"] == "completed",
            receipt_count=int(matches and done["state"] == "completed"),
            facts={"saved": row is not None, "native_record_matches": matches},
        )
        evidence.extend(
            [
                {"phase": "patient_confirmation", "source": "native_api", "independently_confirmed": True},
                {"phase": "readback", "source": "owned_readback"},
            ]
        )
    elif fixture == "cross_owner":
        task = h.start("profile.view")
        response = h.client.get(
            f"/api/agent/workflows/tasks/{task['task_id']}", params={"client_id": "DEMO-workflow-B"}
        )
        common["facts"] = {"foreign_read_denied": response.status_code == 404}
        common["effects"]["cross_owner_reads"] = int(response.status_code == 200)
        evidence.append({"phase": "read", "source": "native_api"})
    else:
        raise ValueError("Unknown offline fixture")
    return common


def run_case(case: EvalCase) -> ObservedRun:
    if case.setup_fixture not in FIXTURE_IDS:
        raise ValueError("Unknown offline fixture")
    if case.environment != "local_memory" or case.setup_fixture == "provider_required":
        return ObservedRun(
            case_id=case.id,
            environment="local_memory",
            execution_mode="records_only",
            facts={},
            effects={},
            explanations=(),
            evidence=(),
            task_complete=False,
            model_requests=0,
        )
    start = perf_counter()
    try:
        with offline_network_guard(), WorkflowHarness(knowledge_v2_enabled=True) as h:
            h._request(
                "PUT", "/api/me/preferences", json={"preferred_language": case.language, "timezone": case.timezone}
            )
            before = clinical(h.snapshot())
            values = execute(case, h)
            unchanged = clinical(h.snapshot()) == before
            values["facts"]["clinical_unchanged"] = unchanged
            values["effects"]["clinical_writes"] = values["effects"].get("clinical_writes", 0) + int(not unchanged)
    except Exception as error:
        values = {
            "environment": "local_memory",
            "facts": {},
            "effects": {},
            "explanations": [],
            "evidence": [],
            "task_complete": False,
            "tool_errors": ["fixture_error:" + type(error).__name__.lower()],
        }
        if isinstance(error, OfflineNetworkDenied):
            values["effects"]["unexpected_provider_call"] = 1
    return ObservedRun(case_id=case.id, latency_ms=(perf_counter() - start) * 1000, model_requests=0, **values)
