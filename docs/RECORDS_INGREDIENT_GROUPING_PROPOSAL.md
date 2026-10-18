# Trusted ingredient grouping: blocked relationship and minimum proposal

Status: proposal only; no schema change, mapping backfill or patient-record merge implemented.

Owner clarification (2026-10-18): Records now groups equal display names for browsing and queries their owned registrations through `medication_name`. This does not require ingredient identity mapping and does not assert ingredient equivalence. The proposal below remains relevant only to future authoritative ingredient grouping; it no longer blocks the requested name-based UI.

## Confirmed local contract

- `patient_medications.product_id` references `medication_products.id`. It is nullable. Regimen versions reference a patient medication; dose occurrences/events reference their regimen. These identities must remain unchanged.
- Migration `202610130001_core.sql` defines product `ingredient_names text[]`, generic name, strength, form, release and market. It does not define an ingredient ID or authoritative product-to-ingredient relationship. Later repository migrations do not introduce that relationship.
- Source extraction `IngredientIdentity.rxcui` exists, but is externally supplied extraction evidence. This repository does not validate its concept type or persist an authoritative ingredient mapping. Reviewing a document does not prove that an extracted RxCUI is a verified ingredient identifier.
- Equal product IDs can identify the same product; different strengths/forms can have different product IDs. Names, substrings, salts, apparent synonyms and product-level RxCUIs do not establish an ingredient group.

Consequently the current read model cannot safely aggregate Amlodipine 5 mg and 10 mg as a verified ingredient group. Actual production rows were not inspected or modified. This limitation is not evidence that those two registrations are clinically different ingredients.

## Minimum implementation requiring separate approval

1. Choose a licensed authoritative ingredient namespace and supported concept types. Define how salts, combinations, release forms, unmapped products and conflicting identifiers are handled; no fuzzy grouping.
2. Establish verified product-to-ingredient mappings with provenance, verification status and source version. Prefer a separately approved additive relation if an existing trusted source cannot supply this through a public read interface. Keep registrations, plans and events untouched. No automatic patient-data backfill or merging.
3. Group by the full verified ingredient-ID set, preserving child product identity/strength/form/release and medication IDs. Unknown/conflicting mappings stay independent. Display safe ingredient names from the verified mapping, not names guessed from registration text.
4. Extend the typed catalogue and read-only history query with server-validated group identity. Resolve only current patient's registration IDs, bind cursors to the group/filter, and preserve the existing two-stream event ordering/pagination. Selecting an individual regimen still narrows the query.
5. Verify distinct strengths/forms, combinations versus single ingredients, similar names with different IDs, unknown mappings, historical product identity, cross-patient rejection and real PostgREST queries before release.

Risk: medium for authoritative mapping/schema, high if incorrectly treated as clinical equivalence. No dose calculations, write APIs, inventory, RLS relaxation or production cleanup are part of this proposal. The current task stops short of implementing it.

## Safe work delivered independently

Search real registration labels using Unicode normalization and case-insensitive matching. Keep native select keyboard/mobile behavior and the all-medicines option. Remove UUIDs from patient labels. Show real source strength separately from per-dose quantity, recorded frequency and actual effective dates. Do not invent an end date or repeat the full plan description under the selector.
