# Draft hard deletion — independent proposal

Status: design only. No deletion API, deletion UI, migration or database deletion has been implemented or executed in this round.

## Why an ordinary DELETE cannot work

- `core_guard_regimen()` in `202610130001_core.sql` rejects every DELETE, including draft plans.
- `core_guard_challenge()` retains confirmation history; `core_freeze_reviewed_source()` freezes reviewed sources/fields even before activation. A reviewed document is not the same as a confirmed active medication.
- `audit_events` has a regimen foreign key and an append-only guard. Removing all linked rows would also require an explicit audit-retention design.
- Migration 015 evidence/source/image relations use owner-scoped `ON DELETE RESTRICT`; evidence/history tables do not grant ordinary client DELETE access. A series of independent PostgREST deletes would be non-atomic and unsafe under activation/source-link races.
- Medication deletion alone cannot safely remove the draft graph. Hiding a row or returning a frontend success is not hard deletion.

## Proposed patient interaction

1. “Delete draft” beside each unfinished source task or saved draft, separate from “Continue”.
2. An accessible confirmation dialog names the medication and explains that the unconfirmed draft and its exclusive source material will be removed. Cancel performs no write. Confirm is disabled while the one deletion request is running.
3. Refresh the authoritative pending list only after the server confirms deletion. Failure keeps the draft visible. A draft confirmed in another tab cannot be deleted and the UI explains the changed state.

## Proposed minimum implementation (requires approval)

- Public preview/result DTOs and a patient-authenticated deletion service; root is a stable task/draft ID, never a medication name. Preview includes a version token and the exact deletable scope. Confirmation must match that snapshot; recheck and lock inside the transaction.
- One narrowly scoped atomic database RPC, using the current patient JWT. Validate ownership on every relation and reject any active, ended or superseded plan; any dose occurrence/event, inventory/care/recognition history; consumed or confirmed challenge; existing protected audit relation; or shared source/attachment that cannot be safely separated.
- An unconfirmed plan version belonging to an already confirmed medication may be deleted as a version only; the parent medication, confirmed plans and shared evidence must stay. Whole new-registration deletion is permitted only when every related plan is unconfirmed and every child is exclusively draft-owned.
- Delete exclusive unfinished tasks, source links, unconfirmed draft versions, source fields/documents and the otherwise unused patient-medication row in one transaction. Necessary pending challenge/session references must be invalidated safely, not replayed. Private storage object removal requires a retryable cleanup design and must never remove a shared object. Database transaction completion is not proof that object storage cleanup succeeded.
- Preserve shared products, confirmed regimens, dose events, inventory, care data, conversations and genuine clinical/audit history. “All related rows” cannot mean deleting shared or confirmed patient data by cascade.
- Additive versioned migration may grant only the narrow operation, not general client table DELETE or wider RLS. Any trigger exception must be restricted to the controlled operation and unconfirmed/exclusive rows. Never use a caller-settable flag alone, disable triggers globally or use service-role frontend access.

## Audit decision that must be settled first

Safe initial scope: refuse hard deletion if protected confirmation/audit/history references exist. This can support simple abandoned drafts, but not every failed or partially confirmed flow.

Recommended full design: remove exclusive draft business data while retaining minimal deletion audit. Existing audit FKs/append-only retention require a separately approved reference/tombstone design; do not null, rewrite or delete existing audit rows as an incidental fix. If the owner instead requires removal of old audit rows too, that is a distinct retention-policy change requiring explicit approval and security review, not an automatic part of the delete button.

## Required acceptance and rollback

- Real isolated PostgreSQL/RLS tests: cross-patient denial, unauthorized direct deletes, pure draft, pending clarification, reviewed-but-unactivated source, shared source/image, active/history refusal, stale preview, activation/delete race, concurrent retry, complete rollback on a failed child delete and no residual exclusive child rows after success.
- Actual browser confirmation/cancel/failure and refresh tests. Compare real DB counts/IDs, not mocked success. Storage cleanup/retry verified separately.
- No production migration or patient cleanup is authorized by this proposal. Local feature implementation/migration files and production migration execution are separate approval scopes.
- Rollback: keep the frontend delete operation disabled/unpublished, revoke the new RPC if required, and restore the prior guarded functions via a tested rollback migration. Deleted data cannot be recreated by rollback; backup/recovery is a separate production prerequisite.

Risk: high for physical deletion, audit retention and concurrent activation. Approval requested for the precise local implementation/isolated-testing scope after the audit decision; no Git commit or deployment implied.


## 2026-10-18 local implementation status

Owner authorized local SQL-controlled deletion and UI changes. Implemented 027 + rollback file, typed owner-scoped deletion service/API, explicit confirmation, and retryable Storage API cleanup. Delete-trigger events were removed; INSERT/UPDATE medical validation remains. Generic table DELETE is revoked. No production SQL was executed. Six real isolated PostgreSQL tests and four HTTP/provider/metadata tests pass.

This is the conservative pure-draft slice, not unrestricted audit deletion: protected audit/history links refuse the whole transaction; shared evidence is retained. Confirmation revalidates current ownership/state under locks; it does not implement a separate versioned preview API. Durable cleanup receipts exist, but a pending-cleanup list after reload is not implemented. Existing active-plan changes still use the reviewed stop/new-version flow; no seamless replacement API was added. New manually/scanned-edited versions carry patient_edited; old records are not backfilled.
