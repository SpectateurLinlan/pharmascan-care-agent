"""Closed capability discovery; no identity or write credentials in model inputs."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CapabilityMode = Literal["read", "workflow", "patient_ui", "device_ui", "navigation"]


class CapabilityAvailability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    workflows_enabled: bool = False
    workflow_unavailable_reason: Literal["feature_disabled", "persistence_not_ready"] = "feature_disabled"
    services: frozenset[str] = frozenset()
    adapters: frozenset[str] = frozenset()
    notification_send_allowed: bool = False
    implemented_capabilities: frozenset[str] | None = None
    disabled_capabilities: frozenset[str] = frozenset()


class CoverageResult(BaseModel):
    """Evidence for one phase in one environment; implementation is not a PASS."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    capability_id: str = Field(pattern=r"^[a-z]+(?:\.[a-z]+)*$")
    case_id: str = Field(min_length=1, max_length=200)
    environment: Literal["local_memory", "local_browser", "recording_port", "provider", "database",
                         "deployed", "physical_device", "real_auth"]
    status: Literal["PASS", "PARTIAL", "NOT_RUN", "UNAVAILABLE", "FAIL"]
    reason: str | None = Field(default=None, min_length=1, max_length=1000)
    evidence_path: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def require_actual_evidence(self):
        if self.status in {"PASS", "PARTIAL"} and not self.evidence_path:
            raise ValueError("A passing or partial case requires actual evidence")
        if self.status != "PASS" and not self.reason:
            raise ValueError("An unrun, limited, unavailable or failed result needs an explicit reason")
        return self


class CapabilityDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str = Field(pattern=r"^[a-z]+(?:\.[a-z]+)*$")
    version: Literal[1] = 1
    title_key: str
    mode: CapabilityMode
    input_schema_id: str
    adapter_key: str
    required_services: frozenset[str] = frozenset()


class CapabilityView(CapabilityDefinition):
    # A registered application adapter is separate from current service,
    # rollout, notification authority and actual acceptance evidence.
    implemented: bool = False
    available: bool
    reason: str | None = None
