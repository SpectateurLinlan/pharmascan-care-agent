"""Fixed owner-JWT native intent commands. No workflow, generic SQL or write retry."""

from ..contracts.native_media_verification import (
    NativeMediaDeleteIntent,
    NativeMediaTicket,
    NativeMediaUploadIntent,
    VerifiedNativeMediaRef,
)
from ..domain.errors import (
    DuplicateEventError,
    NotFoundError,
    ProviderUnavailableError,
    StaleVersionError,
    ValidationError,
)


class SupabaseNativeMediaIntents:
    def __init__(self, data):
        self._data = data

    def _call(self, owner, kind, **values):
        self._data.check_patient(owner)
        raw = self._data.request(
            "POST", "/rest/v1/rpc/assistant_native_media_command", body={"p_command": {"kind": kind, **values}}
        )
        if not isinstance(raw, dict) or set(raw) not in ({"result"}, {"error"}):
            raise ProviderUnavailableError("Native intent result unavailable")
        if "error" in raw:
            errors = {
                "stale": StaleVersionError,
                "not_found": NotFoundError,
                "invalid": ValidationError,
                "duplicate": DuplicateEventError,
            }
            code = raw["error"] if isinstance(raw["error"], str) else "unavailable"
            raise errors.get(code, ProviderUnavailableError)("Native intent changed; inspect its actual result")
        return raw["result"]

    def _prepare(self, owner, intent, *, uploading):
        self._data.check_patient(owner)
        intent = (NativeMediaUploadIntent if uploading else NativeMediaDeleteIntent).model_validate(intent.model_dump())
        if (intent.target.owner if uploading else intent.owner) != owner:
            raise ValidationError("Native intent belongs to another patient")
        raw = self._call(
            owner, "prepare_upload" if uploading else "prepare_delete", intent=intent.model_dump(mode="json")
        )
        try:
            if not isinstance(raw, dict) or set(raw) != {"ticket", "proof"}:
                raise ValueError
            ticket = NativeMediaTicket.model_validate(raw["ticket"])
            target = ticket.target
            if (
                ticket.ticket_id != intent.operation_id
                or target.owner != owner
                or ticket.operation != ("upload" if uploading else "delete")
                or uploading
                and target != intent.target
                or not uploading
                and (target.bucket_id != intent.bucket_id or target.object_ref != intent.object_ref)
            ):
                raise ValueError
            if raw["proof"] is None:
                return ticket
            proof = VerifiedNativeMediaRef.model_validate(raw["proof"])
            if (
                proof.ticket_id != ticket.ticket_id
                or proof.generation != ticket.generation
                or proof.result != ("bytes_verified" if uploading else "absent_after_delete")
            ):
                raise ValueError
            return proof
        except (ValueError, TypeError):
            raise ProviderUnavailableError("Native intent response binding unavailable") from None

    def prepare_upload(self, owner, intent):
        return self._prepare(owner, intent, uploading=True)

    def prepare_delete(self, owner, intent):
        return self._prepare(owner, intent, uploading=False)

    def claim(self, owner, ticket):
        self._data.check_patient(owner)
        ticket = NativeMediaTicket.model_validate(ticket.model_dump())
        if ticket.target.owner != owner:
            raise ValidationError("Native ticket belongs to another patient")
        raw = self._call(
            owner, "claim", ticket_id=str(ticket.ticket_id), nonce=str(ticket.nonce), generation=ticket.generation
        )
        if raw is not True:
            raise ProviderUnavailableError("Native operation was not claimed")

    def settle_delete(self, owner, proof):
        self._data.check_patient(owner)
        proof = VerifiedNativeMediaRef.model_validate(proof.model_dump())
        if proof.result != "absent_after_delete":
            raise ValidationError("Actual independently verified absence required")
        if self._call(owner, "settle_delete", proof=proof.model_dump(mode="json")) is not True:
            raise ProviderUnavailableError("Native deletion settlement unavailable")
