"""Patient JWT SQL operation; storage cleanup uses the Storage API, not SQL."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as SchemaError

from ..contracts.draft_deletion import DraftDeletionResult, DraftKind
from ..contracts.medication_evidence import PrivateImageStore
from ..domain.errors import NotFoundError, ProviderUnavailableError, ValidationError
from .evidence_repos import MemoryEvidenceRepository
from .memory_repos import InMemoryStore
from .supabase_data import SupabaseDataClient


class Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deleted: bool
    medication_deleted: bool
    storage_paths: list[str] = Field(max_length=1000)


class SupabaseDraftDeletion:
    def __init__(self, client: SupabaseDataClient, storage: PrivateImageStore):
        self._client, self._storage = client, storage

    def delete(self, owner: UUID, kind: DraftKind, target: UUID) -> DraftDeletionResult:
        self._client.check_patient(owner)
        try:
            receipt = Receipt.model_validate(
                self._client.request(
                    "POST",
                    "/rest/v1/rpc/delete_unconfirmed_medication",
                    body={"p_kind": kind, "p_id": str(target), "p_confirmed": True},
                )
            )
        except SchemaError as error:
            raise ProviderUnavailableError("Invalid draft deletion response.") from error
        if not receipt.deleted:
            raise ProviderUnavailableError("Draft deletion was not confirmed.")
        pending = False
        for path in receipt.storage_paths:
            if not path.startswith(str(owner) + "/") or ".." in path:
                raise ProviderUnavailableError("Invalid cleanup ownership.")
            try:
                self._storage.delete(path)
                self._client.request(
                    "POST",
                    "/rest/v1/rpc/ack_draft_image_cleanup",
                    body={"p_kind": kind, "p_id": str(target), "p_path": path},
                )
            except ProviderUnavailableError:
                pending = True
        return DraftDeletionResult(medication_deleted=receipt.medication_deleted, cleanup_pending=pending)


class MemoryDraftDeletion:
    """DEMO_ONLY atomic in-process fixture. Real transaction/races tested in SQL."""

    def __init__(self, store: InMemoryStore, evidence: MemoryEvidenceRepository, storage: PrivateImageStore):
        self._store, self._evidence, self._storage = store, evidence, storage

    def delete(self, owner: UUID, kind: DraftKind, target: UUID) -> DraftDeletionResult:
        key = (owner, kind, target)
        if key not in self._store.draft_deletions:
            task = self._evidence.get(owner, "tasks", target) if kind == "source" else None
            plan = self._store.regimens.get((owner, target)) if kind == "draft" else None
            if not task and not plan:
                raise NotFoundError("Draft not found")
            med = task.medication_id if task else plan.patient_medication_id
            versions = [
                r for (p, _), r in self._store.regimens.items() if p == owner and r.patient_medication_id == med
            ]
            whole = not any(r.state in {"active", "ended", "superseded"} for r in versions)
            ids = {r.id for r in versions if whole or r.id == (task.draft_regimen_id if task else target)}
            if any(r.state not in {"draft", "pending_clarification"} for r in versions if r.id in ids):
                raise ValidationError("Confirmed plans cannot be deleted.")
            if any(
                r.regimen_id in ids
                for rows in [self._store.events, self._store.occurrences, self._store.dose_rules]
                for (p, _), r in rows.items()
                if p == owner
            ):
                raise ValidationError("This draft has protected history and cannot be deleted.")
            challenges = [r for (p, _), r in self._store.challenges.items() if p == owner and r.regimen_id in ids]
            if any(r.confirmed_at or r.consumed_at for r in challenges):
                raise ValidationError("This draft has protected history and cannot be deleted.")
            tasks = [
                r
                for r in self._evidence.list(owner, "tasks")
                if r.medication_id == med and (whole or r.id == target or r.draft_regimen_id in ids)
            ]
            srcs = {r.source_id for r in versions if r.id in ids and r.source_id}
            srcs.update(s for r in tasks for s in r.source_ids)
            medication = self._store.medications.get((owner, med))
            if whole and medication and medication.source_id:
                srcs.add(medication.source_id)
            shared = {r.source_id for (p, _), r in self._store.regimens.items() if p == owner and r.id not in ids}
            shared.update(
                r.source_id
                for (p, _), r in self._store.medications.items()
                if p == owner and (r.id != med or not whole)
            )
            for link in self._evidence.list(owner, "sources"):
                if link.medication_id != med:
                    shared.add(link.source_id)
            srcs -= shared
            runs = self._evidence.list(owner, "runs")
            sets = {r.id for r in self._evidence.list(owner, "sets") if r.medication_id == med}
            if any(r.selected_regimen_id in ids or (whole and sets.intersection(r.reference_ids)) for r in runs):
                raise ValidationError("This draft has protected history and cannot be deleted.")
            paths = self._evidence.remove_draft_artifacts(owner, med, whole, {r.id for r in tasks}, srcs)
            for rows in [self._store.challenges, self._store.regimens, self._store.source_fields, self._store.sources]:
                for rowkey, row in list(rows.items()):
                    if rowkey[0] != owner:
                        continue
                    remove = (
                        row.id in ids
                        if rows is self._store.regimens
                        else row.id in srcs
                        if rows is self._store.sources
                        else row.regimen_id in ids
                        if rows is self._store.challenges
                        else row.source_id in srcs
                    )
                    if remove:
                        del rows[rowkey]
            if whole:
                self._store.medications.pop((owner, med), None)
            self._store.draft_deletions[key] = {"medication_deleted": whole, "paths": paths}
        receipt = self._store.draft_deletions[key]
        for path in list(receipt["paths"]):
            try:
                self._storage.delete(path)
                receipt["paths"].remove(path)
            except ProviderUnavailableError:
                continue
        return DraftDeletionResult(
            medication_deleted=receipt["medication_deleted"], cleanup_pending=bool(receipt["paths"])
        )
