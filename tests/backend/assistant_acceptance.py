"""Closed synthetic acceptance orchestration. Importing this module does no I/O."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from time import monotonic as system_monotonic
from typing import Literal

from app.contracts.agent_execution import ExecutionStopped, ProviderUsage
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

Mode = Literal["offline", "provider-memory", "isolated-integration"]
CaseId = Literal[
    "provider.tool_selection",
    "provider.chinese_enrollment",
    "provider.name_choice",
    "provider.source_failure",
    "provider.failure_recovery",
    "provider.independent_confirmation",
]
Reason = Literal[
    "provider_not_enabled",
    "request_budget_missing",
    "provider_configuration_missing",
    "synthetic_fixture_required",
    "isolated_target_unverified",
    "case_budget_missing",
    "time_budget_missing",
    "request_limit",
    "case_limit",
    "time_limit",
    "execution_failed",
    "provider_evidence_missing",
    "objective_not_met",
    "provider_key_missing",
]


class AcceptanceDTO(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class RunnerBudget(AcceptanceDTO):
    max_requests: int = Field(default=0, strict=True, ge=0, le=12)
    max_cases: int = Field(default=0, strict=True, ge=0, le=6)
    max_seconds: int = Field(default=0, strict=True, ge=0, le=120)


class RunnerConfig(AcceptanceDTO):
    mode: Mode = "offline"
    budget: RunnerBudget = Field(default_factory=RunnerBudget)
    synthetic: StrictBool = True
    allow_provider: StrictBool = False
    model: str | None = Field(default=None, max_length=100, pattern=r"^gemini-[a-zA-Z0-9._-]+$")
    api_key_env: str | None = Field(default=None, pattern=r"^MEDITHREAD_ACCEPTANCE_[A-Z0-9_]{1,70}$")


@dataclass(frozen=True)
class AcceptanceScenario:
    id: CaseId
    fixture: str
    language: Literal["en", "zh"] = "en"


SCENARIOS = (
    AcceptanceScenario("provider.tool_selection", "tool_selection"),
    AcceptanceScenario("provider.chinese_enrollment", "manual_enrollment", "zh"),
    AcceptanceScenario("provider.name_choice", "name_confirmation"),
    AcceptanceScenario("provider.source_failure", "photo_failure"),
    AcceptanceScenario("provider.failure_recovery", "provider_failure"),
    AcceptanceScenario("provider.independent_confirmation", "native_observation"),
)


class CaseResult(AcceptanceDTO):
    case_id: CaseId
    status: Literal["passed", "failed", "not_run", "degraded", "unavailable"]
    reason: Reason | None = None
    evidence_layer: Literal["not_run", "local_memory", "recording_port", "provider_memory", "fault_injection"]
    model_success: StrictBool = False
    application_status: Literal["passed", "failed", "degraded", "unavailable"] | None = None
    checks: dict[
        Literal[
            "tool_selected",
            "clinical_unchanged",
            "draft_ready",
            "has_name_choice",
            "original_retained",
            "independent_receipt",
            "fallback_honest",
        ],
        StrictBool,
    ] = Field(default_factory=dict)
    model_requests: int = 0
    real_requests: int = 0
    wire_attempts: int = 0
    returned_model: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9._/-]{1,100}$")
    usage: ProviderUsage | None = None
    latency_ms: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def honest_provider_evidence(self):
        if self.model_success and (
            self.evidence_layer != "provider_memory"
            or self.real_requests < 1
            or self.model_requests < 1
            or self.returned_model is None
        ):
            raise ValueError("Model success requires actual provider evidence")
        return self


class RunnerReport(AcceptanceDTO):
    mode: Mode
    budget: RunnerBudget
    reason: Reason | None = None
    cases: tuple[CaseResult, ...]
    real_requests: int = 0
    wire_attempts: int = 0
    model_requests: int = 0
    user_turns: int = 0
    duration_ms: float = 0
    usage: ProviderUsage | None = None
    usage_responses: int = 0

    @property
    def exit_code(self):
        if self.reason == "execution_failed" or any(case.status == "failed" for case in self.cases):
            return 1
        return 2 if any(case.status != "passed" for case in self.cases) else 0


class RunnerStopped(ExecutionStopped):
    reason = "budget_exceeded"

    def __init__(self, limit_reason: Reason):
        super().__init__()
        self.limit_reason = limit_reason


class RunnerUnavailable(Exception):
    def __init__(self, reason: Reason):
        self.reason = reason


class RunnerLimiter:
    def __init__(self, budget: RunnerBudget, *, monotonic=system_monotonic):
        self.budget, self._now = budget, monotonic
        self.started = monotonic()
        self.deadline = self.started + budget.max_seconds
        self.real_requests = self.model_requests = self.user_turns = self.cases = 0
        self.wire_attempts = 0
        self.usage = None
        self.usage_responses = 0
        self._lock = RLock()

    def check(self):
        if self._now() >= self.deadline:
            raise RunnerStopped("time_limit")

    def remaining(self, native_timeout):
        self.check()
        return min(native_timeout, self.deadline - self._now())

    def begin_case(self):
        with self._lock:
            self.check()
            if self.cases >= self.budget.max_cases:
                raise RunnerStopped("case_limit")
            self.cases += 1

    def user_turn(self):
        with self._lock:
            self.check()
            self.user_turns += 1

    def model_request(self):
        with self._lock:
            self.check()
            self.model_requests += 1

    def before_request(self, *, real=True):
        with self._lock:
            self.check()
            if self.wire_attempts >= self.budget.max_requests:
                raise RunnerStopped("request_limit")
            self.wire_attempts += 1
            self.real_requests += int(real)

    def duration_ms(self):
        return max(0, (self._now() - self.started) * 1000)

    def record_usage(self, usage):
        if usage is not None:
            from app.application.agent_runtime_metadata import combine_usage

            with self._lock:
                self.usage = combine_usage(self.usage, usage)
                self.usage_responses += 1


def denied_reason(config: RunnerConfig) -> Reason | None:
    if not config.synthetic:
        return "synthetic_fixture_required"
    if config.mode == "isolated-integration":
        return "isolated_target_unverified"
    if config.mode == "provider-memory":
        if not config.allow_provider:
            return "provider_not_enabled"
        if not config.budget.max_requests:
            return "request_budget_missing"
        if not config.model or not config.api_key_env:
            return "provider_configuration_missing"
    if not config.budget.max_cases:
        return "case_budget_missing"
    if not config.budget.max_seconds:
        return "time_budget_missing"
    return None


def run_acceptance(
    config: RunnerConfig, *, factory: Callable | None = None, monotonic=system_monotonic
) -> RunnerReport:
    limiter = RunnerLimiter(config.budget, monotonic=monotonic)
    results = []
    reason = denied_reason(config)
    if reason is None:
        if factory is None:
            from .assistant_provider_runtime import AcceptanceRuntime

            factory = AcceptanceRuntime
        try:
            with factory(config, limiter) as runtime:
                for case in SCENARIOS:
                    counts = (limiter.model_requests, limiter.wire_attempts, limiter.real_requests)
                    try:
                        limiter.begin_case()
                        result = runtime.execute(case, limiter)
                        limiter.check()
                        if not isinstance(result, CaseResult) or result.case_id != case.id:
                            raise ValueError("Invalid acceptance result")
                        actual_counts = (
                            limiter.model_requests - counts[0],
                            limiter.wire_attempts - counts[1],
                            limiter.real_requests - counts[2],
                        )
                        if (result.model_requests, result.wire_attempts, result.real_requests) != actual_counts:
                            raise ValueError("Acceptance counters do not match execution")
                        if result.model_success and (config.mode != "provider-memory" or actual_counts[2] < 1):
                            raise ValueError("Provider completion lacks actual external evidence")
                        results.append(result)
                    except RunnerStopped as stop:
                        reason = stop.limit_reason
                        results.append(
                            CaseResult(
                                case_id=case.id,
                                status="not_run",
                                reason=reason,
                                evidence_layer="not_run",
                                model_requests=limiter.model_requests - counts[0],
                                wire_attempts=limiter.wire_attempts - counts[1],
                                real_requests=limiter.real_requests - counts[2],
                            )
                        )
                        break
                    except Exception:
                        results.append(
                            CaseResult(
                                case_id=case.id,
                                status="failed",
                                reason="execution_failed",
                                evidence_layer="local_memory" if config.mode == "offline" else "not_run",
                                model_requests=limiter.model_requests - counts[0],
                                wire_attempts=limiter.wire_attempts - counts[1],
                                real_requests=limiter.real_requests - counts[2],
                            )
                        )
        except RunnerStopped as stop:
            reason = stop.limit_reason
        except RunnerUnavailable as unavailable:
            reason = unavailable.reason
        except Exception:
            reason = "execution_failed"
    completed = {result.case_id for result in results}
    results.extend(
        CaseResult(case_id=case.id, status="not_run", reason=reason, evidence_layer="not_run")
        for case in SCENARIOS
        if case.id not in completed
    )
    return RunnerReport(
        mode=config.mode,
        budget=config.budget,
        reason=reason,
        cases=tuple(results),
        real_requests=limiter.real_requests,
        wire_attempts=limiter.wire_attempts,
        model_requests=limiter.model_requests,
        user_turns=limiter.user_turns,
        duration_ms=limiter.duration_ms(),
        usage=limiter.usage,
        usage_responses=limiter.usage_responses,
    )
