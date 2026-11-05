# Assistant persistence review candidates

Files here are unnumbered, operator-reviewed persistence definitions, outside the
automatic migrations directory. They are not automatically installed by deploying
code. Application to another target still requires target-specific authorization,
backup, privilege checks and acceptance; reading a file grants no authority.

Validation update (2026-11-06): the complete ordered foundation/candidate set was
created in a real Supabase PostgreSQL17.11 transaction and rolled back. The fixed
technical/patient-role readiness readers agreed on an unpublished release; direct
application-table and ordinary clinical definer access was absent for the evidence
login. Changes to the new installation membership's INHERIT/SET options changed
the catalog fingerprint. The checked catalog returned to its original state.
This supersedes earlier NOT_RUN statements only for definition creation and these
specific metadata/permission checks. It does not validate business-function paths,
real patient JWT HTTP admission, clinical writes, Storage, races or recovery.
That initial preflight rolled back all definitions. A separately authorized hosted
installation followed; private target receipts track its amendments and acceptance.
An installation alone does not publish runtime readiness. Hosted acceptance also
exercised bounded SQL transactions, real patient JWTs, private original retention,
cross-owner denials, cancellation cleanup, and native photo/PDF compatibility.
These receipts are target-specific, not a blanket validation of every clinical
path or another installation. Supabase's non-superuser installer
needs temporary owner-role/schema privileges during ownership transfer; remove
these installation privileges before accepting any release. Source checks alone
do not establish those target-specific prerequisites.

Prerequisites (source baselines; inspect each target's actual migration ledger):

- `202610250035_assistant_workflows.sql`: SHA256 `4da7dde8d29aa9efe0604178570be6e7c24749c5191a34186bccafb08476366a`.
- `202610250036_enrollment_workflow_idempotency.sql`: SHA256 `cbdb6a03c8d3f2059907b140bc2b85bc4c8cae0e690947f2b88d32bdbd8cadc2`.

`roles.review.sql` contains no credentials or target-specific CONNECT grant. The
operator must review the exact target ledger, role memberships, PUBLIC/function/
table/default privileges, network/TLS and credential lifecycle under separate
approval. NOINHERIT does not remove PUBLIC privileges. No role may acquire clinical
authority through PUBLIC, SET ROLE, user-controlled JWT GUC or a definer function.

`metadata.up.sql` owns only technical tickets, observations, minimal receipts and
run/event tables. The verification owner owns tickets/observations/run metadata;
the separate workflow owner owns business receipts. Neither the verifier login nor
its definer owner receives clinical table permissions or clinical RPC execution.
Patient identity continues through the verified JWT and domain transactions.

The mutation entry has closed structural/control handlers; its candidate grant is
patient-only. Domain completion is deliberately refused, and run-bound commands
require the separately installed run fence. Composition remains disabled pending
the complete reviewed/actually tested candidate set. Existing generic callback/
terminal-action rejection must not be removed to bypass this. This foundation
does not implement domain receipt publication or physical cleanup.

Unknown Storage observations are append-only alongside a later terminal observation;
one terminal proof per ticket/generation is enforced. Proof is not a clinical result
and does not alone publish a saved attachment or a deleted cleanup receipt. Expiry
does not settle an in-flight request. Later ticket issue/claim/delete exclusion and
reference guards are required before any upload or deletion can be enabled.

`metadata.down.sql` refuses nonempty metadata, has no forced data removal and leaves
the existing workflow, clinical data, Storage, roles and schema intact. Reverse later
candidates first; normal recovery is to disable new entry points and preserve data.
Actual PostgreSQL syntax, RLS, PUBLIC closure, concurrency and rollback are NOT RUN.

`messages.up.sql` is the patient content domain, owned by a separate NOLOGIN
message role. It wraps existing conversation operations and typed session/trace
writes under the workflow/run fence. The evidence login and evidence owner receive
none of these permissions. Source checks are not transaction evidence.

The native `clear_conversation_history()` compatibility definition detaches035
task/control thread FKs before the original history clear, retaining task fields,
clinical data and originals. Its original owner/ACL and reviewed target baseline
must be checked before applying. `messages.down.sql` leaves this compatibility
fence in place while035data remains, removes the new command/policies, and never
drops patient tables. Restoring an older native clear definition needs a separate
review; doing so blindly can strand retained tasks and threads.

`medication.up.sql` adds the closed patient medication write/read boundary,
command fingerprints, native receipt lookup and owner-first compatibility fences.
Preparation, source/name review and independent challenge/activation remain
separate operations. Response-loss reads cannot reprepare/copy an image. A changed
command under the same action key is rejected; applied receipts are retained even
when the current native result becomes unavailable. No Storage HTTP runs in SQL.

Source save additionally requires the I11 fixed
`assistant_native_image_assert_verified(uuid,jsonb,jsonb)` proof resolver; its
absence returns unavailable and rolls back publication. Raw and native-copy
proofs are separate. Native media reference/deletion fences and full metadata
projection equivalence must be reviewed with I11 before enablement. Patient DTO
and recording-wire tests do not prove these PostgreSQL semantics or permissions.

`medication.down.sql` refuses nonempty command/original/native-enrollment metadata
and disables the two new entry points. It retains empty compatibility metadata,
036 columns, statement fences and native activation/delete wrappers. It is not a
full035/036 restore, and its retained dependencies intentionally prevent a blind
foundation teardown. Any further removal needs a reviewed recovery sequence.
Actual SQL syntax, RLS/ACL, lock order, concurrent/response-loss transactions,
native-source materialization and down execution remain **NOT RUN**.

`records.up.sql` separates confirmation preparation, patient-confirmed native
recording, and readback. Original dose events and correction rows stay append-only.
It wraps the existing self-report/late-report routines, preserves unbound native
signatures, and fences bound challenges/events through actual private issue
metadata and current task controls. Patient confirmation after a completed chat
does not inherit the expired run; new run-bound preparation still checks it.
Scheduled preparation accepts an explicit existing occurrence and does not invoke
schedule generation. Ordinary report timestamps come from the server; the existing
late-report rules alone govern historical administration times and corrections.

Record receipts retain only hashes/IDs; single-use tokens are returned once and
never copied into workflow receipts. Record down disables the three new workflow
entry points only after an empty-metadata check and retains native compatibility
fences/helpers/permissions. As with medication down, retained dependencies prevent
an unreviewed full foundation teardown. No audit/history deletion is authorized.
Real PostgreSQL syntax, owner/role/PUBLIC closure, native compatibility, concurrency,
response-loss and recovery behavior are **NOT RUN**; source audits and recording
transport checks do not establish them.

The media candidates are split: `media-verification.up.sql` defines restricted
technical copy/delete observations; `media.up.sql` adds normal patient ticket
issuance, verified source-image adoption and native metadata/task/receipt writes.
The raw original, gallery image, source image and PDF remain distinct purposes.
Cleanup requires an actual independently recorded absence; tombstoning alone
never acknowledges physical deletion. Permanent deleting-key fences remain after
settlement. Normal legacy upload/cleanup callers must be converted and verified
before enabling these candidates; their proof-requiring ACK wrappers cannot be
rolled out independently. The paired downs preserve technical evidence, native
history, reference fences and compatibility dependencies.

`settings.up.sql` follows media and adds preference/profile, consented contact and
feedback transactions. Only permitted native preference columns can be updated;
there is no Auth, contact verification, notification or sharing authority.
Feedback/contact bodies stay in their native owned rows and saved user drafts;
runtime command/receipt metadata contains only bounded IDs/hashes.

`reminders.up.sql` follows settings and adds snooze/settings transactions. Its
original attention boundary projects actual owned rules without generating dose
history. Python/PostgreSQL timezone and interval-anchor parity (including folds,
gaps, half-hour transitions and midnight) must be established on the approved
isolated target. A source inventory does not validate those semantics. Device
subscription/test delivery and calendar export retain their independent existing
boundaries. No candidate installs a worker, sender or schedule.

All three families retain actual SQL/ACL/RLS/native compatibility/concurrency/
recovery acceptance as **NOT RUN**. The typed graph remains disabled until the
complete reviewed candidate set, ordinary caller conversion and target-specific
acceptance are ready. Reading these files authorizes none of those external steps.

The request-local candidate graph now composes all native business consumers,
message/session persistence, durable control, original storage, copy verification
and cleanup. It remains a separate, disabled candidate; ordinary patient requests
do not mount it because configuration or a verifier DSN happens to be present.
Explicit workflow requests mount it only after the separate release admission
described below; ordinary homepage reads never make a verifier connection.

The messages candidate also contains fixed independently confirmed conversation
transitions and browser subscription metadata transitions. Subscription keys stay
in the native private subscription rows; receipts contain only identifiers and a
digest. These functions cannot send notifications or acquire Auth authority.
The originals candidate has a read-only storage access decision tied to actual
owned claims and persistent deleting exclusions. The medication candidate has a
read-only draft deletion result projection. Draft metadata deletion with unknown
physical cleanup remains pending; it cannot call the legacy Storage-ACK path or
claim file absence. Existing reference and writer exclusions remain authoritative.

## Source-bound release admission (review only)

`runtime-readiness.up.sql` follows the complete candidate set, including native
media compatibility. It adds an operator-owned, RLS-protected release ledger and
two fixed read-only readers. Installation publishes no accepted record. Patient
and verifier roles receive no ledger write permission. The five technical
observation commands remain unchanged; the verifier gains only one metadata read.

After separately authorized target acceptance, an operator publishes the actual
running application hash, observed catalog digest, unique release UUID, retained
acceptance evidence digest and native compatibility outcome. Both patient RPC and
restricted connection must report this same release. The catalog fingerprint
covers function definitions/ACLs, tables/RLS, columns, constraint validation,
index validity, trigger definitions/enabled state, rewrite rules, policies,
schemas/default ACLs and role flags/memberships; covered DDL/ACL drift
invalidates admission. It reads no patient records or uploaded bytes. This marker
records prior operator acceptance; it does not replace JWT, RLS, independent
confirmation or transaction guards, and is not a complete runtime security audit.

The ordinary evidence upload/update/delete and unfinished-draft deletion entry
points require the same admission when native verification is configured. The
native bridge can operate independently with Assistant workflows disabled; it
retains its existing verified native services and does not expose workflow tools. Bound
Assistant writes always fail closed when admission is unavailable. Progress is
mounted only when its separate flag is enabled. No readiness environment bypass
is supported. A constructed `rollout_ready=False` candidate remains distinct from
an admitted request container.

Active-incident recovery revokes the release under an authorized operator change
and disables workflow/progress entry, preserving all clinical records, original
bytes, receipts and release history. Retain native verification so ordinary native
writes refuse the revoked release, or explicitly pause those writers. The paired down
refuses **any** release history, including revoked rows; never delete history to
force rollback. Setting the native flag false selects legacy media writers;
that requires separate compatibility review after new receipts exist. Disabling
a flag alone is not that review.

SQL syntax/privileges/target pairing, private Storage, races, native compatibility,
provider/deployed/device verification remain **NOT RUN**. Offline source tests and
the inspector inventory are preparation evidence only, not rollout permission.
