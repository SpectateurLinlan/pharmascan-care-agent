"""Collected source references only; patient review stays outside model input."""

from uuid import UUID

from pydantic import Field, model_validator

from .assistant_workflows import WorkflowDTO


class SourceTargetFields(WorkflowDTO):
    source_task_id: UUID | None = None
    expected_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def paired_target_version(self):
        if (self.source_task_id is None) != (self.expected_version is None):
            raise ValueError("Source registration and current version are required together")
        return self


class SourceAddFields(SourceTargetFields):
    medication_id: UUID | None = None
    source_attachment_id: UUID | None = None


class SourceReviewFields(SourceTargetFields):
    page: int = Field(default=0, ge=0, le=1000000)


SOURCE_SCHEMAS = {"medication.source.add": SourceAddFields, "medication.source.review": SourceReviewFields}
