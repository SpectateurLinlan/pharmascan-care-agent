"""DEMO_ONLY memory HTTP progress, never provider or SQL acceptance."""

import json
from dataclasses import replace
from threading import Event
from uuid import uuid4

from app.transport.app_factory import create_app
from app.transport.container import build_container
from fastapi.testclient import TestClient

PATH = "/api/agent/workflows"
PARAMS = {"client_id": "DEMO-progress"}


def test_progress_is_explicit_and_defaults_off():
    with TestClient(create_app(build_container(assistant_workflows_enabled=True))) as client:
        manifest = client.get(PATH + "/capabilities", params=PARAMS).json()
        assert "progress_enabled" in manifest, "progress availability must be explicit"
        assert manifest["progress_enabled"] is False
        assert client.get(PATH + f"/runs/{uuid4()}", params=PARAMS).status_code == 503


def test_runtime_flag_requires_explicit_enable_and_composed_workflows(monkeypatch, tmp_path):
    from app.config import Settings

    monkeypatch.delenv("ASSISTANT_PROGRESS_ENABLED", raising=False)
    assert Settings.from_env(env_file=tmp_path / "absent.env").assistant_progress_enabled is False
    monkeypatch.setenv("ASSISTANT_PROGRESS_ENABLED", "true")
    assert Settings.from_env(env_file=tmp_path / "absent.env").assistant_progress_enabled is True
    c = build_container(assistant_progress_enabled=True)
    assert c.assistant_execution is None
    if c.close_request:
        c.close_request()


def payload():
    return {"text": "List my medications", "workspace_id": str(uuid4()), "client_turn_id": str(uuid4())}


def frames(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_stream_matches_normal_validated_response_without_persisting_reply():
    c = build_container(assistant_workflows_enabled=True, assistant_progress_enabled=True)
    with TestClient(create_app(c)) as client:
        normal = client.post(PATH + "/messages", params=PARAMS, json=payload())
        assert normal.status_code == 200 and normal.headers["X-Agent-Run-ID"]
        run = str(uuid4())
        streamed = client.post(PATH + "/messages/stream", params=PARAMS, json={**payload(), "run_id": run})
        assert streamed.status_code == 200 and "text/event-stream" in streamed.headers["content-type"]
        rows = frames(streamed)
        events = [r for r in rows if "sequence" in r]
        assert events[0]["kind"] == "run_started" and events[-1]["kind"] == "run_completed"
        assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
        final = next(r["result"] for r in rows if "result" in r)
        assert final["reply"]["message"] == normal.json()["reply"]["message"]
        assert final["reply"]["mode"] == normal.json()["reply"]["mode"]
        snapshot = client.get(PATH + f"/runs/{run}", params=PARAMS).json()
        # A controlled workflow may answer directly without an agent tool.
        assert any(e["kind"] == "step_completed" and e["action_key"] == "application" for e in snapshot["events"])
        assert "message" not in json.dumps(snapshot) and "List my medications" not in json.dumps(snapshot)
        assert (
            client.post(PATH + "/messages/stream", params=PARAMS, json={**payload(), "run_id": run}).status_code == 409
        )
        foreign = {"client_id": "DEMO-other"}
        assert client.get(PATH + f"/runs/{run}", params=foreign).status_code == 404
        assert client.post(PATH + f"/runs/{run}/cancel", params=foreign).status_code == 404
        assert client.post(PATH + f"/runs/{run}/cancel", params=PARAMS).json()["status"] == "completed"


def test_stream_failure_is_terminal_and_does_not_expose_exception(monkeypatch):
    c = build_container(assistant_workflows_enabled=True, assistant_progress_enabled=True)
    from app.application.assistant_messages import AssistantMessageService

    def fail(*_args, **_kwargs):
        raise RuntimeError("PRIVATE_PROVIDER_TOKEN")

    monkeypatch.setattr(AssistantMessageService, "handle", fail)
    with TestClient(create_app(c)) as client:
        response = client.post(PATH + "/messages/stream", params=PARAMS, json={**payload(), "run_id": str(uuid4())})
        rows = frames(response)
        assert rows[-1]["kind"] == "run_failed"
        assert not any("result" in row for row in rows)
        assert "PRIVATE" not in response.text


def test_resource_stays_open_during_stream_work_and_closes_once(monkeypatch):
    from app.application.assistant_messages import AssistantMessageService

    root = build_container(assistant_workflows_enabled=True, assistant_progress_enabled=True)
    closed = []
    scoped = replace(root, patient_factory=None, close_request=lambda: closed.append(1))
    root.patient_factory = lambda principal: scoped
    original = AssistantMessageService.handle

    def checked(self, *args, **kwargs):
        assert not closed, "middleware closed resources before stream consumption"
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AssistantMessageService, "handle", checked)
    with TestClient(create_app(root)) as client:
        response = client.post(PATH + "/messages/stream", params=PARAMS, json={**payload(), "run_id": str(uuid4())})
        assert frames(response)[-1].get("result")
        assert closed == [1]


def test_cancel_in_flight_stops_following_tool_and_result(monkeypatch):
    from app.application.assistant_messages import AssistantMessageService
    from app.contracts.agent_execution import execution_step

    c = build_container(assistant_workflows_enabled=True, assistant_progress_enabled=True)
    entered, release = Event(), Event()
    touched = []

    def paused(*_args, **_kwargs):
        with execution_step("tool"):
            entered.set()
            assert release.wait(3)
        touched.append("late")

    monkeypatch.setattr(AssistantMessageService, "handle", paused)
    from concurrent.futures import ThreadPoolExecutor

    with TestClient(create_app(c)) as client, ThreadPoolExecutor() as pool:
        run = str(uuid4())
        future = pool.submit(client.post, PATH + "/messages/stream", params=PARAMS, json={**payload(), "run_id": run})
        assert entered.wait(3)
        try:
            assert client.post(PATH + f"/runs/{run}/cancel", params=PARAMS).json()["status"] == "cancelling"
        finally:
            release.set()
        rows = frames(future.result(timeout=4))
        assert rows[-1]["kind"] == "run_cancelled" and not touched
        assert not any("result" in row for row in rows)


def test_disconnect_waits_for_worker_then_closes_resources_once():
    import asyncio

    from app.contracts.agent_execution import execution_step
    from app.transport.workflow_stream import WorkflowStreamResponse

    c = build_container(assistant_workflows_enabled=True, assistant_progress_enabled=True)
    service = c.assistant_execution
    owner, run = uuid4(), uuid4()
    service.start(owner, run)
    entered, release, returned = Event(), Event(), Event()
    closed = []

    def work():
        try:
            with execution_step("tool"):
                entered.set()
                assert release.wait(4)
        finally:
            returned.set()

    def close():
        assert returned.is_set(), "closed while SDK/tool worker was still running"
        closed.append(1)

    async def exercise():
        response = WorkflowStreamResponse(service=service, owner=owner, run_id=run, work=work, close_request=close)

        async def receive():
            assert await asyncio.to_thread(entered.wait, 3)
            return {"type": "http.disconnect"}

        async def send(_message):
            pass

        async def release_when_cancelled():
            for _ in range(200):
                if service.read(owner, run).status == "cancelling":
                    assert not closed
                    release.set()
                    return
                await asyncio.sleep(0.005)
            release.set()
            raise AssertionError("disconnect did not request cancellation")

        monitor = asyncio.create_task(release_when_cancelled())
        try:
            await response({"type": "http", "asgi": {"spec_version": "2.0"}}, receive, send)
            await monitor
        finally:
            release.set()

    asyncio.run(exercise())
    assert closed == [1] and service.read(owner, run).status == "cancelled"


def test_failed_stream_closes_scoped_resources_once(monkeypatch):
    from app.application.assistant_messages import AssistantMessageService

    root = build_container(assistant_workflows_enabled=True, assistant_progress_enabled=True)
    closed = []
    scoped = replace(root, patient_factory=None, close_request=lambda: closed.append(1))
    root.patient_factory = lambda principal: scoped

    def fail(*_args, **_kwargs):
        assert not closed
        raise RuntimeError("DEMO error")

    monkeypatch.setattr(AssistantMessageService, "handle", fail)
    with TestClient(create_app(root)) as client:
        response = client.post(PATH + "/messages/stream", params=PARAMS, json={**payload(), "run_id": str(uuid4())})
        assert frames(response)[-1]["kind"] == "run_failed"
        assert closed == [1]
