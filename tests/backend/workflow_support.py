"""DEMO_ONLY HTTP harness using real services and explicit external fixtures."""

from time import monotonic
from uuid import uuid4

import httpx
from app.application.medication_understanding import MedicationUnderstandingService
from app.infrastructure.openfda_knowledge import OpenFDAKnowledge
from app.transport.app_factory import create_app
from app.transport.container import build_container, demo_patient_id
from fastapi.testclient import TestClient

from .conftest import CountingIdGenerator, FixedClock


class WorkflowHarness:
    def __init__(self, *, source_preview=None, original_storage=None, source_results=None, knowledge_v2_enabled=False):
        self.clock = FixedClock()
        self.source_calls = []
        if source_results is not None:
            from app.application.source_preview import SourcePreviewService

            queue = list(source_results)
            calls = self.source_calls

            class QueuedSourceProvider:
                def extract_medication_source(self, **kwargs):
                    calls.append(kwargs)
                    if not queue:
                        raise AssertionError("Unexpected extraction replay")
                    result = queue.pop(0)
                    if isinstance(result, Exception):
                        raise result
                    return result.model_copy(
                        update={
                            "source_document_id": kwargs["source_document_id"],
                            "source_kind": kwargs["source_kind"],
                        }
                    )

            source_preview = SourcePreviewService(provider=QueuedSourceProvider(), ids=CountingIdGenerator())
        self.container = build_container(
            clock=self.clock,
            ids=CountingIdGenerator(),
            assistant_workflows_enabled=True,
            knowledge_v2_enabled=knowledge_v2_enabled,
            workflow_preview=source_preview,
            workflow_storage=original_storage,
        )
        if self.container.close_request:
            self.container.close_request()
        self.knowledge_requests = []

        def public_label_fixture(request):
            self.knowledge_requests.append(request)
            return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})

        self.knowledge_http = httpx.Client(transport=httpx.MockTransport(public_label_fixture))
        self.container.medication_understanding = MedicationUnderstandingService(
            self.container.enrollment,
            OpenFDAKnowledge(self.knowledge_http, self.clock, monotonic=monotonic),
            self.clock,
        )
        self.container.close_request = self.knowledge_http.close
        self.workspace_id = str(uuid4())
        self.owner_ids = {name: demo_patient_id("DEMO-workflow-" + name) for name in ("A", "B")}
        self.client = TestClient(create_app(container=self.container))
        self.client.__enter__()
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if not self._closed:
            self.client.__exit__(None, None, None)
            self.knowledge_http.close()
            self._closed = True

    def _request(self, method, path, *, owner="A", **kwargs):
        url = httpx.URL(path)
        params = url.params.merge(kwargs.pop("params", {})).merge({"client_id": "DEMO-workflow-" + owner})
        response = self.client.request(method, str(url.copy_with(query=None)), params=params, **kwargs)
        assert response.status_code == 200, (method, path, response.status_code, response.text)
        return response.json()

    def start(self, capability_id, values=None, save=True):
        return self._request(
            "POST",
            "/api/agent/workflows/tasks",
            json={
                "capability_id": capability_id,
                "workspace_id": self.workspace_id,
                "values": values or {},
                "save_mode": "allowed" if save else "ephemeral",
                "client_event_id": str(uuid4()),
            },
        )

    def view(self, task_id, owner="A"):
        return self._request("GET", "/api/agent/workflows/tasks/" + task_id, owner=owner)

    def event(self, task_id, kind, values=None, revision=None, event_id=None):
        if revision is None:
            revision = self.view(task_id)["revision"]
        return self._request(
            "POST",
            f"/api/agent/workflows/tasks/{task_id}/events",
            json={
                "event_id": event_id or str(uuid4()),
                "expected_revision": revision,
                "kind": kind,
                "values": values or {},
            },
        )

    def upload(self, task_id, content, mime="image/png"):
        revision = self.view(task_id)["revision"]
        return self._request(
            "PUT",
            f"/api/agent/workflows/tasks/{task_id}/attachments/{uuid4()}"
            f"?expected_revision={revision}&source_kind=pharmacy_label",
            content=content,
            headers={"Content-Type": mime, "X-Stage2-Consent": "true"},
        )

    def snapshot(self):
        store = self.container.store
        history = []
        for owner in self.owner_ids.values():
            before = None
            seen = set()
            while True:
                page = self.container.conversation_history.page(owner, before=before)
                history.extend(row.model_dump(mode="json") for row in page.entries)
                if page.next_before is None:
                    break
                assert page.next_before not in seen, "History pagination did not advance"
                seen.add(page.next_before)
                before = page.next_before
            service = self.container.conversation_threads
            thread_before = None
            thread_cursors = set()
            while True:
                threads = service.list(owner, before=thread_before, limit=50)
                for thread in threads.entries:
                    message_before = None
                    message_cursors = set()
                    while True:
                        page = service.page(owner, thread.id, before=message_before, limit=100)
                        history.extend(row.model_dump(mode="json") for row in page.entries)
                        if page.next_before is None:
                            break
                        assert page.next_before not in message_cursors, "Message pagination did not advance"
                        message_cursors.add(page.next_before)
                        message_before = page.next_before
                if threads.next_before is None:
                    break
                assert threads.next_before not in thread_cursors, "Thread pagination did not advance"
                thread_cursors.add(threads.next_before)
                thread_before = threads.next_before
        return {
            "tasks": [
                row.model_dump(mode="json")
                for owner in self.owner_ids.values()
                for row in self.container.assistant_workflows.saved_tasks(owner)
            ],
            "workflow_controls": [
                row
                for owner in self.owner_ids.values()
                for row in self.container.assistant_workflows.persistence_snapshot(owner)["controls"]
            ],
            "workflow_event_results": [
                row
                for owner in self.owner_ids.values()
                for row in self.container.assistant_workflows.persistence_snapshot(owner)["event_results"]
            ],
            "originals": [
                row.model_dump(mode="json", exclude={"extraction"})
                for owner in self.owner_ids.values()
                for row in self.container.assistant_attachments.originals(owner)
            ],
            "history": history,
            "medications": [row.model_dump(mode="json") for row in store.medications.values()],
            "regimens": [row.model_dump(mode="json") for row in store.regimens.values()],
            "dose_events": [row.model_dump(mode="json") for row in store.events.values()],
            "sources": [row.model_dump(mode="json") for row in store.sources.values()],
            "source_fields": [row.model_dump(mode="json") for row in store.source_fields.values()],
            "sessions": [row.model_dump(mode="json") for row in store.sessions.values()],
            "tool_traces": [row.model_dump(mode="json") for row in store.traces.values()],
        }

    def read_original(self, attachment_id, owner="A"):
        row = next(row for row in self.snapshot()["originals"] if row["id"] == attachment_id)
        response = self.client.get(
            f"/api/agent/workflows/tasks/{row['task_id']}/attachments/{attachment_id}",
            params={"client_id": "DEMO-workflow-" + owner},
        )
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        return response.content

    def seed_reviewed_medication(self):
        session = self._request("POST", "/api/demo/start", json={"client_id": "DEMO-workflow-A"})
        draft = self._request(
            "POST",
            "/api/medications/drafts",
            json={
                "medication_name": "DEMO-workflow-medicine",
                "dose_amount": 1,
                "dose_unit": "tablet",
                "frequency_kind": "daily",
                "frequency_local_times": ["20:00"],
            },
        )
        self._request("POST", f"/api/medications/drafts/{draft['source_id']}/review", json={"field_ids": None})
        return {**draft, "session_id": session["session_id"]}
