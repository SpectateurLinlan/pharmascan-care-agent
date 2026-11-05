"""Compare independent technical release evidence without granting patient access."""

from dataclasses import dataclass, field

from ..contracts.workflow_runtime import (
    RUNTIME_RELEASE_CONTRACT,
    RuntimeReadinessPort,
    RuntimeReleaseSnapshot,
    WorkflowAdmission,
    unavailable_admission,
)
from ..domain.errors import ProviderUnavailableError


@dataclass(frozen=True, repr=False)
class WorkflowRuntime:
    """Request-owned ports; construction performs no technical I/O."""

    patient: RuntimeReadinessPort = field(repr=False)
    technical: RuntimeReadinessPort | None = field(repr=False)
    application_hash: str | None
    native_media_enabled: bool
    progress_enabled: bool

    def check(self) -> WorkflowAdmission:
        if not self.native_media_enabled:
            return unavailable_admission("native_media_not_ready")
        if self.technical is None:
            return unavailable_admission("verification_unavailable")
        if not self.application_hash:
            return unavailable_admission("application_unidentified")
        try:
            # Two fixed, bounded reads. Each adapter closes its own resources.
            patient = self.patient.read_release(timeout_seconds=4.0)
            technical = self.technical.read_release(timeout_seconds=4.0)
        except (ProviderUnavailableError, OSError, TimeoutError, ValueError):
            return unavailable_admission("readiness_unavailable")
        return compare_release_snapshots(
            patient,
            technical,
            expected_application_hash=self.application_hash,
        )


def compare_release_snapshots(
    patient: RuntimeReleaseSnapshot,
    technical: RuntimeReleaseSnapshot,
    *,
    expected_application_hash: str | None,
) -> WorkflowAdmission:
    if not expected_application_hash:
        return unavailable_admission("application_unidentified")
    if any(row.contract_version != RUNTIME_RELEASE_CONTRACT for row in (patient, technical)):
        return unavailable_admission("release_contract_mismatch")
    if not patient.accepted or not technical.accepted:
        return unavailable_admission("release_not_accepted")
    if any(row.application_hash != expected_application_hash for row in (patient, technical)):
        return unavailable_admission("application_mismatch")
    if not patient.native_media_ready or not technical.native_media_ready:
        return unavailable_admission("native_media_not_ready")
    if patient.release_id != technical.release_id or patient.catalog_digest != technical.catalog_digest:
        return unavailable_admission("release_target_mismatch")
    return WorkflowAdmission(available=True, reason="ready")
