# Records medication history query

The patient frontend calls typed FastAPI APIs, never Supabase tables directly.

- `GET /api/me/medication-history/catalogue`: owned medication registrations and their regimen versions. Identity is by UUID, not name. A regimen version is not automatically a treatment course.
- `GET /api/me/medication-history`: optional `medication_name`, `medication_id`, `regimen_id`, `range_kind` (`7`, `30`, `90`, `custom`, `all`, `plan`), custom `start`/`end` local dates, `cursor`, `limit` (default 5, maximum 50).

Default: all medications, all related plans, 30 patient-local calendar days through now. Custom end dates are inclusive local dates converted to an exclusive next-midnight UTC boundary. Plan scope uses actual effective_from/effective_to, capped at now. Missing plan start is disclosed. Future doses never appear as history.

Only existing dose occurrences and saved self-reports are queried. Missing historical schedules are not generated. `all` means all stored available history, not proof that every historical dose was scheduled or reported. The older dose-history API remains unchanged and is not used by this Records view.

Scheduled rows use due_at as their corresponding medication time. Reports join by owned occurrence ID even when submitted later. Unscheduled rows use event_time; existing write paths may assign server report time, so this is not proof of ingestion time. created_at is separately exposed as submitted_at. A missing report stays unrecorded, never inferred taken or missed.

Results merge two descending keyset streams with stable IDs and a snapshot cutoff. next_cursor is present only when more real fetched rows exist. A cursor is bound to owner and filters; authorization is independently applied on every query. The frontend resets pagination on filter changes and ignores stale in-flight replies.

The Supabase adapter uses the existing patient JWT client and owner filters/RLS. Metadata is bounded to 2,000 rows; more than 100 confirmed plans within any query scope requires choosing a narrower medicine or plan. Large event histories page on the server rather than loading all events. Errors/truncation fail explicitly instead of being rendered as unrecorded doses.

No migrations or production data changes are required. Deploy backend APIs before publishing the frontend. Legacy clients remain compatible. Local acceptance uses explicit DEMO fixtures and mocked provider contracts; production PostgREST execution is a separate verification step.


## Display-name grouping (owner clarification, 2026-10-18)

The selector shows each equal medication name once, ignoring case, repeated whitespace and Unicode compatibility variants. It never removes strength words, expands abbreviations or performs fuzzy/ingredient matching. All original registration IDs remain in the catalogue and database. Strength, form, dose, frequency and effective dates distinguish the child plans; no UUID or independent-registration label is shown to the patient.

`medication_name` resolves exact normalized names only among the authenticated patient's medications, then queries the associated regimen IDs. Selecting a specific regimen narrows that group. Mismatched/foreign names or plans are rejected; name filters are bound into pagination cursors. Thus Amlodipine5/10mg registrations with the same display_name can be browsed together without asserting medical equivalence or changing a product identity.

Authoritative ingredient-based grouping remains a separate optional proposal, not a dependency for display-name browsing. See [the proposal](RECORDS_INGREDIENT_GROUPING_PROPOSAL.md). No schema changes or patient-record merging were performed.


## Confirmation boundary (2026-10-18)

Only active, ended and superseded plans and their medication registrations are eligible for this history catalogue/query. Draft, pending-clarification and source-only registrations are not confirmed medications and do not appear, including direct-ID requests or same-name grouping. Reviewing a source or issuing/cancelling a challenge does not activate a medication. Existing confirmed historical plans remain available; they are not deleted when retired.
