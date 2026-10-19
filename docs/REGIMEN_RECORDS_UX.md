# Regimen Records — 2026-10-19 owner-approved supplement

The authenticated owner diagnostic returned six regimen versions: five active and one ended. Gallery used elapsed course dates to call active records historical; the terminal-only History entry excluded those same records. This was a presentation inconsistency, not authority to change lifecycle state.

| Acceptance | Implementation / verification |
|---|---|
| All Courses default, Currently Tracked, Ended | Confirmed chain tips; active retained even after planned end; draft/pending stay in setup |
| Genuine version chains | supersedes_id with matching patient-medication ID and increasing version; never group by name or strength text |
| Elapsed planned end | Patient IANA calendar; label “Planned end date passed; still tracked”; no lifecycle write |
| Gallery consistency | Active elapsed-date records remain currently tracked; visual-check eligibility restrictions unchanged |
| Search, sorting and navigation | Existing mounted component and past-medicines route retained; Back/Forward and reload covered |
| Source/version integrity | Original regimen, dose reports, database and migration history unchanged; superseded versions remain accessible through existing detail |

Local verification: Regimen Records/Navigation component19 passed; related MedicationEvidence28 passed in the earlier47-case run (one Chinese expectation corrected in the19-case rerun); backend medication-evidence40 passed; actual React/Chromium route journeys2 passed with synthetic Auth/HTTP. Typecheck and lint passed. These are not production authenticated acceptance or real notification tests. Initial fixture failures were corrected by creating a valid start/end interval before activation and advancing the synthetic clock, rather than editing an active regimen.

The previous History-only requirements are superseded by this dated owner supplement. No automatic active→ended transition, medication-name deduplication, new lifecycle, migration, production operation or deployment is authorized. A local commit was subsequently authorized; unrelated worktree features must remain outside its index.


Selective-commit verification: an isolated checkout of the staged index (without unrelated Library/Care Task/migration work) passed TypeScript, ESLint, production build,7 Regimen Records component tests,6 affected Medicines navigation tests and27 backend medication-evidence tests. Its real Chromium Back/Forward/direct-refresh journey passed; mobile390 and desktop1280 screenshots were inspected. These subset counts overlap the unified-worktree counts above and are not additive. An extra run of the staged baseline's unrelated periodic-summary test failed on its existing count-text expectation; Summary source and that assertion are unchanged by this patch. The unified working-tree19-case navigation/records suite passed. This local commit is not approval of a full Release Candidate or deployment.

The commit includes only15 selected paths and minimal compatibility prerequisites (supersedes_id in the existing read DTO, mounted records route and scoped styles/localisation). Shared files were staged selectively; the remaining Library/PDF, Care Tasks, inventory,030–033 migrations, diagnostics and repository consolidation work remains uncommitted. No production records, flags, schema or Secrets were changed.
