"""Explicit general education query, separate from workflow preparation."""

from pydantic import Field, field_validator

from .assistant_workflows import EphemeralPayload, WorkflowDTO


class KnowledgeFields(WorkflowDTO):
    medication_name: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("medication_name")
    @classmethod
    def name_text(cls, value):
        if value is not None and (not value.strip() or any(ord(char) < 32 for char in value)):
            raise ValueError("Enter a medicine name without control characters")
        return value.strip() if value is not None else None


class KnowledgeQueryRequest(WorkflowDTO):
    expected_revision: int = Field(strict=True, ge=1)
    ephemeral: EphemeralPayload | None = None
    candidate_id: str | None = Field(default=None, min_length=1, max_length=200)
