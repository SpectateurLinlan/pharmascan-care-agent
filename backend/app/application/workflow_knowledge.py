"""Explicit source lookup; answers never become saved workflow payloads."""

from uuid import UUID

from ..contracts.knowledge_workflow import KnowledgeFields, KnowledgeQueryRequest
from ..contracts.medication_knowledge import MedicationUnderstanding
from ..contracts.medication_names import NameQuery
from ..domain.errors import StaleVersionError, ValidationError
from .assistant_workflows import WorkflowService
from .medication_names import MedicationNameResolver
from .medication_understanding import MedicationUnderstandingService


class WorkflowKnowledgeService:
    def __init__(
        self,
        *,
        workflows: WorkflowService,
        understanding: MedicationUnderstandingService,
        resolver: MedicationNameResolver,
    ):
        self.workflows, self.understanding, self.resolver = workflows, understanding, resolver

    def query(self, owner: UUID, task_id: UUID, request: KnowledgeQueryRequest) -> MedicationUnderstanding:
        context, values = self.workflows.read_only_input(
            owner, task_id, request.expected_revision, "medication.knowledge", request.ephemeral
        )
        if not isinstance(values, KnowledgeFields) or values.medication_name is None:
            raise ValidationError("Enter a medicine name before querying")
        resolution = self.resolver.resolve(NameQuery(text=values.medication_name, purpose="general_use"), ())
        name = resolution.canonical_name or values.medication_name
        if resolution.status in {"needs_confirmation", "ambiguous"}:
            candidate = next((row for row in resolution.candidates if row.id == request.candidate_id), None)
            if candidate is None:
                raise ValidationError("Confirm one of the current suggested medicine names first")
            name = candidate.canonical_name
        elif request.candidate_id is not None:
            raise ValidationError("This query does not have a pending name choice")
        result = self.understanding.explain(
            patient_id=owner,
            medication_name=name,
            question="general_use",
            language=context.language,
            timezone=context.timezone,
        )
        current = self.workflows.read_only_input(
            owner, task_id, request.expected_revision, "medication.knowledge", request.ephemeral
        )
        if current != (context, values):
            raise StaleVersionError("The query changed while reading the public source")
        return result
