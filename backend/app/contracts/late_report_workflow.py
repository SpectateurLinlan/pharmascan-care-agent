"""Historical review selection only; patient report contents never enter tools."""

from uuid import UUID

from pydantic import Field, model_validator

from .assistant_workflows import WorkflowDTO


class LateReviewFields(WorkflowDTO):
    occurrence_id: UUID | None = None
    expected_version: int | None = Field(default=None, strict=True, ge=1, le=101)
    expected_report_id: UUID | None = None
    page: int = Field(default=0, strict=True, ge=0, le=100000)

    @model_validator(mode="after")
    def paired(self):
        if (self.occurrence_id is None) != (self.expected_version is None):
            raise ValueError("Choose the occurrence and current report generation together")
        if self.expected_report_id is not None and self.occurrence_id is None:
            raise ValueError("Choose the occurrence before its current report")
        return self


LATE_REVIEW_SCHEMAS = dict.fromkeys(("dose.late.review", "dose.correction.review"), LateReviewFields)
