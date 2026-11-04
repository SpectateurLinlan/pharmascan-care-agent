"""Atomic local plan-change review/activation; never a remote transaction claim."""

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from ..contracts.dto import RegimenVersionDTO
from ..domain.errors import StaleVersionError, ValidationError
from .memory_repos import InMemoryStore

T = TypeVar("T")


class MemoryPlanChangeReviewTransaction:
    def __init__(self, store: InMemoryStore):
        self._store = store

    def run(self, owner: UUID, regimen: RegimenVersionDTO, write: Callable[[], T]) -> T:
        # The existing current workflow/control guard holds its lock first.
        # Callbacks are fixed enrollment use cases, never serialized or user code.
        store = self._store
        with store.clinical.lock:
            actual = store.regimens.get((owner, regimen.id))
            if actual is None or actual != regimen or regimen.patient_id != owner:
                raise StaleVersionError("The prepared plan changed; reopen its current review")
            if regimen.supersedes_id and regimen.state.value in {"draft", "pending_clarification"}:
                old = store.regimens.get((owner, regimen.supersedes_id))
                if (
                    old is None
                    or old.patient_medication_id != regimen.patient_medication_id
                    or old.state.value != "active"
                ):
                    raise StaleVersionError("The original active plan changed; review the new version again")
            tables = (
                store.sources,
                store.source_fields,
                store.medications,
                store.regimens,
                store.dose_rules,
                store.occurrences,
                store.challenges,
            )
            before = tuple(table.rows for table in tables)
            staged = tuple(rows.copy() for rows in before)
            revisions = store.clinical.revisions
            staged_revisions = revisions.copy()
            for table, rows in zip(tables, staged, strict=True):
                table.rows = rows
            store.clinical.revisions = staged_revisions
            try:
                result = write()
                for table, rows in zip(tables, before, strict=True):
                    if {key: row for key, row in table.items() if key[0] != owner} != {
                        key: row for key, row in rows.items() if key[0] != owner
                    }:
                        raise ValidationError("Plan review cannot change another patient's records")
                return result
            except BaseException:
                for table, rows in zip(tables, before, strict=True):
                    table.rows = rows
                store.clinical.revisions = revisions
                raise
