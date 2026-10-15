# Stage2 label instruction gaps — owner handoff

Date: 2026-10-14 (Asia/Singapore). This file requests owner-side improvements; it does not change the frozen v0.8.0 external contract.

## Observed application boundary

`/v1/read-label` can return product identity and `Printed.value`/`Printed.line` directions, dispensed quantity, label date and expiry. The current strict adapter exposes `dose_amount`, `frequency`, `administration_times` and `duration` as null. No validated structured food instruction exists. The upstream currently announces v0.9.0; read-only compatibility is separately verified, while the external v0.8.0 snapshot remains unchanged.

Consequently, the app displays original directions and explicit missing-field placeholders. Patient-reviewed input remains necessary for per-dose amount, daily/weekly times, days/start/end and before/after/with-food instructions. It does not infer a patient dose from product strength, dispense quantity, label date or expiry date.

## Requested owner improvements (next explicitly versioned contract)

| Capability | Proposed evidence-bearing output | Fail-closed requirement |
| --- | --- | --- |
| Per-dose instruction | amount + unit + exact printed evidence | `500 mg` product strength is not automatically a prescribed dose; distinguish one tablet from one mg. |
| Frequency | explicit daily count, weekdays or interval + evidence | Twice daily does not supply clock times; do not invent them. Preserve PRN and conditional/maximum wording. |
| Course | explicit duration value/unit, explicit start/end if printed + evidence | Duration alone does not give start date. Fill/expiry dates are not treatment dates. No inferred indefinite course. |
| Food | before/after/with/no food restriction + evidence | Missing stays null. Preserve conflicts and conditional wording rather than choosing an interpretation. |
| Review | per-field presence/ambiguity, source-line IDs, original directions | OCR/extracted instructions are suggestions until patient review; cannot activate regimen or record intake. |

Keep product identity and personal regimen evidence separate. Include example payloads/OpenAPI, null/missing cases and evidence locators for each structured field. Ambiguous ranges, multiple medicines, multilingual directions, conflicting schedules and partial/unreadable labels require review/abstention. Detect count and visual similarity must not determine medication dose, safety or ingestion.

Acceptance examples: synthetic English `Take one tablet twice daily after food for 7 days`; synthetic Chinese equivalent; PRN with maximum wording; missing duration; strength-only packaging; quantity-only label; explicit stop date; contradictory/blurred directions. The owner must supply real examples and validation evidence, not a fabricated successful OCR result.

## Mobile receiver already available

Enrollment has editable dose/unit, daily/selected-weekday clock slots, number of days with explicitly supplied start date, inclusive last day, food instruction and PRN controls. Source preview has corresponding missing-field slots and preserves original printed directions. Persistence stores reviewed source fields and course bounds; activation/self-report guards remain mandatory. A future typed adapter may populate reviewable proposals only after the new response contract is inspected. No unsupported field is currently silently accepted or automatically activated.

## Application-side receiver update (2026-10-15)

Progressive source tasks now keep multiple original extractions and separate product_missing/required regimen fields. A narrow deterministic parser proposes explicitly printed numeric tablet/capsule quantity, HH:MM daily times, literal food wording and explicit Start/End dates. Explicit duration plus explicit start yields a reviewable inclusive end; duration without start requires patient review of start/end before activation. It never uses fill/expiry dates or supply quantity. This does not implement the requested general multilingual/conditional structured Stage2 extraction. PDF parsing and whole-blister matching remain owner/application gaps. Frozen v0.8.0 contract unchanged.

## 0.10.0 receiver and observed gaps (2026-10-15)

The supplied0.10.0 snapshot now defines the structured fields requested above; the application receiver and review mapping are implemented. Earlier statements that no structured fields exist are historical. See STAGE2_V010_UPGRADE.md for current integration. Real synthetic sticker OCR returned dose1tablet/twice daily/after_food; a separate duration line stayed in cautions with instructions.duration=null. A strength-only box was classified dispensing and missed a separate-line ER marker, causing inconsistent RxNorm product suggestions. These are model-response gaps, not permission to fill absent facts or auto-resolve conflict. Text/scanned PDF application support and whole-blister matching remain incomplete. Safety unknown-name mapping/coverage requires further owner evaluation before patient enablement.
