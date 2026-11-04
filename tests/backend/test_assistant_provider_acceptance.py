"""SDK replay tests and a SEPARATELY opted-in live-memory entry point."""

import os

import httpx
import pytest

from . import assistant_provider_runtime as runtime
from .assistant_acceptance import SCENARIOS, RunnerBudget, RunnerConfig, RunnerLimiter, RunnerStopped


def test_acceptance_transport_available():
    assert hasattr(runtime, "AcceptanceTransport"), "Acceptance wire guard is missing"


def test_direct_adapter_cannot_bypass_configuration_gates():
    from .assistant_acceptance import RunnerUnavailable

    with pytest.raises(RunnerUnavailable):
        with runtime.AcceptanceRuntime(RunnerConfig(mode="isolated-integration"), limiter()):
            pytest.fail("unverified isolated adapter started")


def limiter(requests=2, seconds=120):
    return RunnerLimiter(RunnerBudget(max_cases=6, max_requests=requests, max_seconds=seconds))


def test_wire_cap_stops_before_delegate_and_denies_other_origins():
    seen = []
    transport = runtime.AcceptanceTransport(
        limiter(requests=1), httpx.MockTransport(lambda request: (seen.append(1), httpx.Response(200))[1])
    )
    with httpx.Client(transport=transport, follow_redirects=False) as client:
        assert (
            client.post("https://generativelanguage.googleapis.com/v1/interactions", content=b"DEMO").status_code == 200
        )
        with pytest.raises(RunnerStopped):
            client.post("https://generativelanguage.googleapis.com/v1/interactions", content=b"DEMO")
        with pytest.raises(ValueError):
            client.post("https://production.example.invalid/v1/interactions", content=b"DEMO")
    assert len(seen) == 1


def test_wire_input_limit_and_time_check_happen_before_send():
    ticks = [0.0]
    budget = RunnerLimiter(RunnerBudget(max_cases=1, max_requests=2, max_seconds=2), monotonic=lambda: ticks[0])
    seen = []
    transport = runtime.AcceptanceTransport(
        budget, httpx.MockTransport(lambda request: (seen.append(1), httpx.Response(200))[1])
    )
    with httpx.Client(transport=transport) as client:
        with pytest.raises(ValueError):
            client.post("https://generativelanguage.googleapis.com/v1/interactions", content=b"x" * 65537)
        ticks[0] = 2
        with pytest.raises(RunnerStopped):
            client.post("https://generativelanguage.googleapis.com/v1/interactions", content=b"DEMO")
    assert not seen and budget.real_requests == 0


def provider_config():
    return RunnerConfig(
        mode="provider-memory",
        allow_provider=True,
        model="gemini-demo",
        api_key_env="MEDITHREAD_ACCEPTANCE_KEY",
        budget=RunnerBudget(max_cases=6, max_requests=12, max_seconds=120),
    )


def test_real_sdk_replay_selects_real_tool_but_is_not_live_provider_evidence(monkeypatch):
    monkeypatch.setenv("MEDITHREAD_ACCEPTANCE_KEY", "DEMO_NOT_A_REAL_KEY")
    seen = []

    def replay(request):
        seen.append(request)
        steps = (
            [{"type": "function_call", "id": "DEMO-list", "name": "list_active_medications", "arguments": {}}]
            if len(seen) == 1
            else []
        )
        return httpx.Response(
            200,
            json={
                "id": "DEMO",
                "status": "completed",
                "model": "gemini-demo-returned",
                "steps": steps,
                "output_text": "" if steps else "No saved medication entries were returned.",
                "usage": {"total_input_tokens": 4, "total_output_tokens": 2, "total_tokens": 6},
            },
        )

    budget = limiter(requests=12)
    with runtime.AcceptanceRuntime(
        provider_config(), budget, transport_factory=lambda: httpx.MockTransport(replay), simulated=True
    ) as adapter:
        result = adapter.execute(SCENARIOS[0], budget)
    assert len(seen) == 2 and result.checks["tool_selected"] and result.checks["clinical_unchanged"]
    assert result.model_requests == 2 and result.wire_attempts == 2 and result.real_requests == 0
    assert result.usage.total_tokens == 12
    assert result.evidence_layer == "recording_port" and result.model_success is False
    assert result.status == "not_run" and result.reason == "provider_evidence_missing"
    assert "DEMO_NOT_A_REAL_KEY" not in result.model_dump_json()


def test_provider_failure_never_counts_as_success_and_keeps_actual_attempts(monkeypatch):
    monkeypatch.setenv("MEDITHREAD_ACCEPTANCE_KEY", "DEMO_NOT_A_REAL_KEY")
    attempts = []

    def replay(request):
        attempts.append(1)
        return httpx.Response(503, json={"error": {"message": "PRIVATE_PROVIDER_BODY"}})

    budget = limiter(requests=1)
    with runtime.AcceptanceRuntime(
        provider_config(), budget, transport_factory=lambda: httpx.MockTransport(replay), simulated=True
    ) as adapter:
        with pytest.raises(RunnerStopped):
            adapter.execute(SCENARIOS[0], budget)
    assert len(attempts) == 1 and budget.wire_attempts == 1 and budget.real_requests == 0


def test_late_sdk_usage_is_retained_even_when_deadline_stops_the_answer(monkeypatch):
    monkeypatch.setenv("MEDITHREAD_ACCEPTANCE_KEY", "DEMO_NOT_A_REAL_KEY")
    ticks = [0.0]
    budget = RunnerLimiter(RunnerBudget(max_cases=6, max_requests=12, max_seconds=3), monotonic=lambda: ticks[0])

    def replay(request):
        ticks[0] = 3.1
        return httpx.Response(
            200,
            json={
                "id": "DEMO",
                "status": "completed",
                "model": "gemini-demo-returned",
                "steps": [],
                "usage": {"total_input_tokens": 4, "total_output_tokens": 2, "total_tokens": 6},
            },
        )

    with runtime.AcceptanceRuntime(
        provider_config(), budget, transport_factory=lambda: httpx.MockTransport(replay), simulated=True
    ) as adapter:
        with pytest.raises(RunnerStopped):
            adapter.execute(SCENARIOS[0], budget)
    assert budget.wire_attempts == 1 and budget.real_requests == 0
    assert budget.usage is not None, "Late actual SDK usage was discarded"
    assert budget.usage.total_tokens == 6 and budget.usage_responses == 1


def test_global_remaining_time_caps_each_sdk_request(monkeypatch):
    monkeypatch.setenv("MEDITHREAD_ACCEPTANCE_KEY", "DEMO_NOT_A_REAL_KEY")
    ticks, timeouts = [0.0], []
    budget = RunnerLimiter(RunnerBudget(max_cases=6, max_requests=12, max_seconds=3), monotonic=lambda: ticks[0])

    def replay(request):
        timeouts.append(request.extensions["timeout"]["read"])
        ticks[0] = 2.5
        steps = (
            [{"type": "function_call", "id": "DEMO-list", "name": "list_active_medications", "arguments": {}}]
            if len(timeouts) == 1
            else []
        )
        return httpx.Response(
            200,
            json={
                "id": "DEMO",
                "status": "completed",
                "model": "gemini-demo-returned",
                "steps": steps,
                "output_text": "" if steps else "No entries returned.",
            },
        )

    with runtime.AcceptanceRuntime(
        provider_config(), budget, transport_factory=lambda: httpx.MockTransport(replay), simulated=True
    ) as adapter:
        result = adapter.execute(SCENARIOS[0], budget)
    assert timeouts == [3, 0.5] and result.wire_attempts == 2
    assert result.usage is None and budget.usage is None


@pytest.mark.skipif(
    os.environ.get("RUN_ASSISTANT_PROVIDER_ACCEPTANCE") != "1",
    reason="Separate live opt-in and explicit config required",
)
def test_live_provider_memory_acceptance():
    # No Settings.from_env/root dotenv; the file must contain explicit bounds,
    # allow_provider, model, and a separately named acceptance-key variable.
    from pathlib import Path

    from .assistant_acceptance import run_acceptance

    config = RunnerConfig.model_validate_json(
        Path(os.environ["MEDITHREAD_ACCEPTANCE_CONFIG"]).read_text(encoding="utf-8")
    )
    assert config.mode == "provider-memory" and config.allow_provider
    report = run_acceptance(config)
    assert report.cases[0].model_success and report.real_requests <= config.budget.max_requests
    assert not any(case.status == "failed" for case in report.cases)
