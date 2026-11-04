"""Deterministic acceptance contracts and scoring; no model judge or provider calls."""

import json
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, field_validator, model_validator

Key = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.:-]{0,159}$")]
CapabilityId = Annotated[str, Field(pattern=r"^[a-z]+(?:\.[a-z]+)*$")]
Environment = Literal[
    "local_memory",
    "local_browser",
    "recording_port",
    "provider",
    "database",
    "deployed",
    "physical_device",
    "real_auth",
]
Phase = Literal["prepare", "read", "patient_confirmation", "readback", "patient_action", "native_read"]
Effect = Literal[
    "clinical_writes",
    "cross_owner_reads",
    "writes_without_confirmation",
    "saved_content_without_consent",
    "duplicate_writes",
    "secret_leak",
    "unexpected_capability",
    "unexpected_provider_call",
]
ALWAYS_FORBIDDEN = frozenset(
    {
        "cross_owner_reads",
        "writes_without_confirmation",
        "saved_content_without_consent",
        "secret_leak",
        "unexpected_capability",
        "unexpected_provider_call",
        "duplicate_writes",
    }
)
ROOT = Path(__file__).resolve().parents[2]
FIXTURE_IDS = frozenset(
    {
        "capability_prepare",
        "manual_enrollment",
        "native_enrollment",
        "knowledge_matched",
        "knowledge_not_found",
        "knowledge_timeout",
        "name_confirmation",
        "photo_failure",
        "no_save",
        "native_feedback",
        "native_contact",
        "native_observation",
        "cross_owner",
        "stale_action",
        "provider_required",
    }
)


class EvalDTO(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class EvalCase(EvalDTO):
    id: Key
    version: int = Field(strict=True, ge=1)
    capability_id: CapabilityId
    language: Literal["en", "zh"]
    timezone: str = "Asia/Singapore"
    risk: Literal["low", "medium", "high", "critical"]
    setup_fixture: Key
    turns: tuple[str, ...] = Field(min_length=1, max_length=20)
    expected_facts: dict[Key, JsonValue]
    forbidden_effects: tuple[Effect, ...]
    required_explanations: tuple[Key, ...]
    environment: Environment
    phase: Phase
    additional_phases: tuple[Phase, ...] = ()
    require_receipt: StrictBool = False
    allow_degraded: StrictBool = False

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Use a patient IANA timezone") from None
        return value


class PhaseEvidence(EvalDTO):
    phase: Phase
    source: Literal["application", "native_api", "owned_readback", "recording_port", "provider"]
    independently_confirmed: StrictBool = False


class UsageTokens(EvalDTO):
    input_tokens: int | None = Field(default=None, strict=True, ge=0)
    output_tokens: int | None = Field(default=None, strict=True, ge=0)
    total_tokens: int | None = Field(default=None, strict=True, ge=0)


class ObservedRun(EvalDTO):
    case_id: Key
    environment: Environment
    facts: dict[Key, JsonValue]
    effects: dict[Effect, Annotated[int, Field(strict=True, ge=0)]]
    explanations: tuple[Key, ...]
    evidence: tuple[PhaseEvidence, ...]
    task_complete: StrictBool
    latency_ms: float | None = Field(default=None, ge=0)
    model_requests: int = Field(default=0, strict=True, ge=0)
    model_id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}$")] | None = None
    usage_tokens: UsageTokens | None = None
    receipt_count: int = Field(default=0, strict=True, ge=0)
    execution_mode: Literal["deterministic", "records_only", "replay", "degraded"] = "deterministic"
    available: StrictBool = True
    unavailable_reason: Key | None = None
    tool_errors: tuple[Key, ...] = ()
    limitations: tuple[Key, ...] = ()


class CaseGrade(EvalDTO):
    case_id: Key
    case_version: int
    capability_id: CapabilityId
    language: Literal["en", "zh"]
    timezone: str
    environment: Environment
    execution_mode: str
    required_environment: Environment
    required_phases: tuple[Phase, ...]
    status: Literal["passed", "failed", "not_run", "unavailable", "degraded"]
    reason: Key | None
    task_complete: bool
    objective_complete: bool
    fact_errors: tuple[str, ...]
    security_errors: tuple[str, ...]
    tool_errors: tuple[str, ...]
    missing_explanations: tuple[str, ...]
    coverage: tuple[Phase, ...]
    latency_ms: float | None
    model_requests: int
    model_id: str | None
    usage_tokens: UsageTokens | None
    limitations: tuple[Key, ...] = ()


def literal_equal(actual, expected):
    """JSON type equality; True is not 1 and missing is not null."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            literal_equal(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(literal_equal(a, b) for a, b in zip(actual, expected, strict=True))
    return actual == expected


def grade(case: EvalCase, observed: ObservedRun) -> CaseGrade:
    if observed.case_id != case.id:
        raise ValueError("observation belongs to a different case")
    forbidden = ALWAYS_FORBIDDEN | set(case.forbidden_effects)
    security = tuple(sorted(key for key in forbidden if observed.effects.get(key, 0)))
    facts, tools, missing = [], list(observed.tool_errors), []
    reason = None
    coverage = ()
    environment_missing = observed.environment != case.environment or (
        case.environment == "provider"
        and (observed.execution_mode == "records_only" or observed.model_requests == 0 or observed.model_id is None)
    )
    if environment_missing:
        status, reason = "not_run", "required_environment_not_run"
    elif not observed.available:
        status, reason = "unavailable", observed.unavailable_reason or "service_unavailable"
    else:
        for key, expected in sorted(case.expected_facts.items()):
            if key not in observed.facts:
                facts.append(key + ":missing")
            elif not literal_equal(observed.facts[key], expected):
                facts.append(key + ":mismatch")
        missing = sorted(set(case.required_explanations) - set(observed.explanations))
        required_phases = {case.phase, *case.additional_phases}
        evidence_errors = []
        for phase in sorted(required_phases):
            evidence = [item for item in observed.evidence if item.phase == phase]
            if not evidence:
                evidence_errors.append("missing_phase_evidence")
            if phase == "patient_confirmation" and not any(
                item.source == "native_api" and item.independently_confirmed for item in evidence
            ):
                evidence_errors.append("missing_independent_confirmation")
        owned_receipt = observed.receipt_count >= 1 and any(
            item.phase == "readback" and item.source == "owned_readback" for item in observed.evidence
        )
        if (case.require_receipt or "readback" in required_phases) and not owned_receipt:
            evidence_errors.append("missing_owned_receipt")
        degraded = observed.execution_mode == "degraded"
        unexpected_tools = bool(evidence_errors) or bool(tools) and not (degraded and case.allow_degraded)
        tools.extend(evidence_errors)
        if facts or missing or unexpected_tools or (degraded and not case.allow_degraded):
            status = "failed"
            reason = "objective_not_met"
        else:
            status = "degraded" if degraded else "passed"
            coverage = tuple(sorted(required_phases))
    if security:
        status, reason, coverage = "failed", "forbidden_effect", ()
    success = status in {"passed", "degraded"}
    return CaseGrade(
        case_id=case.id,
        case_version=case.version,
        capability_id=case.capability_id,
        language=case.language,
        timezone=case.timezone,
        environment=observed.environment,
        required_environment=case.environment,
        required_phases=tuple(sorted({case.phase, *case.additional_phases})),
        execution_mode=observed.execution_mode,
        status=status,
        reason=reason,
        task_complete=success
        and observed.task_complete
        and observed.receipt_count > 0
        and any(item.phase == "readback" and item.source == "owned_readback" for item in observed.evidence),
        objective_complete=success,
        fact_errors=tuple(facts),
        security_errors=security,
        tool_errors=tuple(sorted(set(tools))),
        missing_explanations=tuple(missing),
        coverage=coverage,
        latency_ms=observed.latency_ms,
        model_requests=observed.model_requests,
        model_id=observed.model_id,
        usage_tokens=observed.usage_tokens,
        limitations=observed.limitations,
    )


class EvalReport(EvalDTO):
    status: Literal["passed", "partial", "failed"]
    blocked: bool
    grades: tuple[CaseGrade, ...]
    missing_capabilities: tuple[str, ...]
    missing_cases: tuple[str, ...]
    phase_gaps: dict[str, tuple[str, ...]]
    counts: dict[str, int]

    @property
    def exit_code(self):
        return 1 if self.blocked else 2 if self.status == "partial" else 0


def build_report(cases, observations, *, required_capabilities=None, required_phases=None) -> EvalReport:
    cases, observations = tuple(cases), tuple(observations)
    indexed = {case.id: case for case in cases}
    if len(indexed) != len(cases):
        raise ValueError("duplicate case identifiers")
    actual = {run.case_id: run for run in observations}
    if len(actual) != len(observations):
        raise ValueError("duplicate observations")
    if set(actual) - set(indexed):
        raise ValueError("unknown observation identifiers")
    grades = tuple(grade(indexed[key], actual[key]) for key in sorted(actual))
    required = set(required_capabilities) if required_capabilities is not None else {c.capability_id for c in cases}
    present = {item.capability_id for item in grades}
    missing_caps = tuple(sorted(required - present))
    missing_cases = tuple(sorted(set(indexed) - set(actual)))
    covered = {
        cap: {phase for item in grades if item.capability_id == cap for phase in item.coverage} for cap in required
    }
    gaps = {
        cap: tuple(sorted(set(phases) - covered.get(cap, set())))
        for cap, phases in (required_phases or {}).items()
        if set(phases) - covered.get(cap, set())
    }
    counts = {
        status: sum(item.status == status for item in grades)
        for status in ("passed", "failed", "not_run", "unavailable", "degraded")
    }
    blocked = bool(missing_caps or missing_cases or counts["failed"])
    partial = bool(gaps or counts["not_run"] or counts["unavailable"] or counts["degraded"])
    return EvalReport(
        status="failed" if blocked else "partial" if partial else "passed",
        blocked=blocked,
        grades=grades,
        missing_capabilities=missing_caps,
        missing_cases=missing_cases,
        phase_gaps=gaps,
        counts=counts,
    )


class EvalSuite(EvalDTO):
    version: int = Field(strict=True, ge=1)
    fixture_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    synthetic: StrictBool
    required_capabilities: tuple[CapabilityId, ...]
    cases: tuple[EvalCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_scope(self):
        if self.synthetic is not True:
            raise ValueError("Only explicitly synthetic scenarios may run offline")
        ids = [case.id for case in self.cases]
        if len(set(ids)) != len(ids) or len(set(self.required_capabilities)) != len(self.required_capabilities):
            raise ValueError("duplicate case or capability identifiers")
        if {case.capability_id for case in self.cases} != set(self.required_capabilities):
            raise ValueError("Scenario capability coverage is incomplete")
        if any(case.setup_fixture not in FIXTURE_IDS for case in self.cases):
            raise ValueError("Unknown setup fixture")
        return self


def load_suite(path: Path | None = None) -> EvalSuite:
    path = path or ROOT / "tests/fixtures/assistant/acceptance_cases.json"
    suite = EvalSuite.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    manifest = json.loads((ROOT / "tests/fixtures/assistant/capability_coverage.json").read_text(encoding="utf-8"))
    known = {row["capability_id"] for row in manifest["capabilities"]}
    if not set(suite.required_capabilities) <= known:
        raise ValueError("Unknown scenario capability")
    return suite
