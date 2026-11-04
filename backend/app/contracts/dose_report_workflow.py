"""A report workflow selects an owned plan, never the patient's confirmation."""

from uuid import UUID

from pydantic import Field, model_validator

from .assistant_workflows import WorkflowDTO


class DoseReportFields(WorkflowDTO):
    regimen_id: UUID | None = None
    expected_version: int | None = Field(default=None, strict=True, ge=1)
    page: int = Field(default=0, strict=True, ge=0, le=100000)

    @model_validator(mode="after")
    def paired(self):
        if (self.regimen_id is None) != (self.expected_version is None):
            raise ValueError("Choose the plan and its version together")
        return self


REPORT_SCHEMAS = {"dose.report": DoseReportFields, "dose.prn.report": DoseReportFields}
