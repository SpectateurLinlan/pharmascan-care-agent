# Historical dose self-report — proposal, not implemented

## Existing contract

- A dose event has separate `event_time` and `created_at` internally. A scheduled event also binds an immutable `occurrence_id` and its `due_at` to a regimen ID.
- `POST /api/doses/{occurrence_id}/report/challenge` and `/report` enforce patient identity, an explicit confirmation challenge, repeat-safe keys and no second report for an already reported occurrence.
- The HTTP report route sets `event_time` to server time. The history response exposes `due_at` and `event_time`, but not `created_at`, event ID or an explicit self-report source.
- `check_dose_write_preconditions` accepts only active regimens. Historical ended/superseded plans cannot be backfilled through the current policy. Scheduled course membership is evaluated using the occurrence date, not the report date.
- The review summary `course` request selects a regimen ID and restricts results to that plan; it does not aggregate every version in a treatment course. The UI now states this limitation.

## Proposed separately authorized slice

1. Define whether reported time means the patient's claimed intake time, or simply the submission time. Keep scheduled `due_at`, claimed event time (if supported), and server-owned `created_at` distinct.
2. Expose event ID, server submission time and a constant patient-self-report source in the read contract. Show those in the review and resulting history; never let the client supply submission time or patient identity.
3. Offer only persisted, owned, unreported past occurrences. Do not reconstruct missing historical schedules or allow arbitrary regimen/date combinations. Keep PRN reports a separate workflow.
4. Decide explicitly whether ended/superseded plans may receive historical reports. Review application policy and database guards together; do not merely bypass the current active-plan check. Any migration or RLS change requires separate approval before implementation.
5. Bind the exact occurrence, status and (if added) claimed time to the confirmation. Reject existing-event conflicts, cross-owner requests, future times and disallowed plan states. Preserve existing reports and audit; corrections require their own design.
6. Check inventory consumers before enabling a late report: a past dose report must not silently change present stock. Reuse existing confirmation and idempotency only after their full payload bindings are verified.

## Acceptance and rollback

Test all three self-reported states, local time/DST, old/current plans in one course and different courses, creation/submission timestamps, duplicate/replayed/conflicting requests, cross-patient access, concurrent writes, unchanged existing events, future schedules and inventory. Roll back the isolated slice; never delete previously saved patient reports.

No backfill endpoint, write control, migration, RLS change or production operation is included in the UX polish commit. This proposal needs owner approval before backend work.
