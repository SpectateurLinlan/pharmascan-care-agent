# Medication Understanding interface

The read-only `MedicationUnderstandingService.explain` separates US general-label
information from the patient's current reviewed instructions. No migration, external
training dataset, vector database, frontend modification or new HTTP endpoint is required.

## Ownership and interface

- Contracts: `app.contracts.medication_knowledge` defines the provider protocol,
  product-only query, label citations and `MedicationUnderstanding` result.
- Application: `app.application.medication_understanding` reads the existing public
  enrollment interface; it has no medication, dose-event or task mutation capability.
- Infrastructure: `app.infrastructure.openfda_knowledge.OpenFDAKnowledge` receives a
  dedicated HTTP client, wall clock and monotonic time source at composition root.
- Agent: the allowlisted `get_medication_understanding` accepts optional owned
  `medication_id` / `medication_name` and `question` (`general_use`,
  `personal_instructions`, `personal_reason`). It does not accept patient identity,
  form/route guesses, dosage, confirmation or SQL arguments. Identity comes from
  the existing verified request context. The existing `get_long_term_care` read-audit
  group records the alias; `payload.action` identifies the actual capability and
  the redacted audit state is `medication_understanding`. No DB tool enum changes.

Existing `POST /api/agent/messages` and response fields remain compatible:

```text
tool_traces[].tool_name = "get_long_term_care"
tool_traces[].payload.action = "get_medication_understanding"
tool_traces[].payload.question
tool_traces[].payload.general_knowledge
tool_traces[].payload.personal_instructions
tool_traces[].payload.personal_indication = null
tool_traces[].payload.patient_safe_summary
```

`general_knowledge.status` is `matched`, `no_reliable_match` or `unavailable`;
`reason` identifies missing evidence, mismatch/conflict or provider failure. An
unavailable provider gives a blocked tool result with `PROVIDER_UNAVAILABLE` and
a deterministic abstention. It never becomes a fabricated citation/model answer.
General-use requests do not send the personal regimen to the knowledge provider.

Each general source includes `source_name`, `market=US`, UUID `set_id`, UUID
`label_id`, `version`, `effective_time`, `retrieved_at`, `url`, `api_url` and
`sections[]` (`field`, `text`, `truncated`). `effective_time` is the label effective
date, not a claimed independent FDA validation date. DailyMed Set ID links may
evolve; the API link uses the retrieved record ID. Historical availability is not
guaranteed. No durable source cache or snapshot repository is introduced.

`personal_instructions` includes `regimen_id`, `version`, `source_document_id`,
`review_status`, `source_kind`, unchanged dose/unit/frequency/PRN/food/route/course
fields, and available `original_instructions` / `original_line`. Missing values
remain null. Patient review is never upgraded to professional verification.
`personal_indication` remains null: the current data model does not establish a
clinician-confirmed personal prescribing reason. A general indication or printed
label indication is insufficient to establish that fact.

## Matching and failure rules

One HTTPS request per provider invocation; eight bounded candidates, 3 MB maximum
decoded response, six-second HTTP operation timeouts and a 12-second streamed
request budget (checked between reads; an in-flight read is bounded by its HTTP
timeout). No automatic retry, redirect following, arbitrary URL or API key.
The existing Agent tool/turn budgets and quota continue to apply; at most four
tool calls per turn. No patient identity, symptoms or whole medication list enters
the FDA query. No cross-patient or global mutable cache is used.

All returned candidates are validated before selection. The matcher requires a
known form, route and release type, exact harmonized generic/brand name, complete
ingredient set when supplied, matching known RxCUI, and matching supported
single-component strength when supplied. It checks textual dosage-form/release
evidence and rejects ambiguous forms, unsupported concentrations, combination
strength strings, salt-name mismatches and incompatible formulations. Missing
harmonized fields or names not mapped exactly cause abstention. This intentionally
does not cover every Singapore brand. A bare name without reliable reviewed product
details requests clarification rather than inventing a route/form.

Within a Set ID the latest numeric version is used; conflicting equal versions or
future labels are rejected. Across matched candidates, all recognized direct use
statements must agree after limited grammatical/name normalization. Unrecognized
wording or disagreement abstains. The result quotes one supported use, explicitly a
partial explanation rather than a complete indications list or safety review. It
matches a US label product family, never proves the exact Singapore product identity.

Supported evidence fields are `indications_and_usage`, `purpose`,
`information_for_patients`, `boxed_warning` and `warnings_and_cautions` when present.
`dosage_and_administration` is parsed at the adapter boundary but deliberately never
used to fill a personal dose. Personal-instruction queries make **zero FDA calls**
and require an unarchived medication, reviewed identity/source and current active
regimen within its effective/course dates. No strength-to-dose conversion occurs.

Chinese output uses controlled translations for two explicitly recognized statement
patterns (hypertension/lowering blood pressure; adult type-2 glycemic-control adjunct
to diet/exercise). Other use wording stays in original English with
`translation_status=original_english_only` and an explicit translation limitation.
Original excerpts, identifiers and units remain available. Gemini cannot paraphrase
or add facts to the deterministic `patient_safe_summary`.

## Minimum future frontend integration

Continue using the existing Agent message endpoint. Show the existing response text;
when the above payload action is present, optionally group general knowledge and
reviewed personal instructions separately. Render source links from `sources[]` with
market, effective date, version, section name and truncation marker. Show unknown
personal indication explicitly. Do not display internal JSON, infer that `matched`
means safe to take, present excerpts as complete warnings, or translate missing
content. Existing frontend files and API fields were not changed by this work.

## Source rights and limits

Data provided by the U.S. Food and Drug Administration (openFDA).
[API overview](https://open.fda.gov/apis/drug/label/),
[fields](https://open.fda.gov/apis/drug/label/searchable-fields/),
[terms](https://open.fda.gov/terms/).
The terms generally apply CC0/public-domain treatment, with explicit exceptions for
third-party copyrighted material. Manufacturer-submitted SPL contents are not all
independently verified or FDA-approved. This implementation retrieves limited
on-demand excerpts and citations, builds no redistributed corpus/embeddings, and
does not claim blanket commercial rights to every label. Operators must respect
third-party restrictions, service limits and the prohibition on relying on openFDA
for medical-care decisions. No MedlinePlus/ASHP or HealthHub content is imported.

## Verification

Default synthetic tests: `tests/backend/test_medication_understanding.py`.
One-request opt-in smoke: `RUN_OPENFDA_LIVE=1 python -m pytest
tests/backend/test_openfda_live.py -q`; default execution skips it. It sends no
patient record. Ignored live evidence is written under `outputs/medication-understanding`.
Mock model I/O proves tool grounding, not live Gemini selection/translation quality.

Existing care/health/review services remain authoritative. The only related change
adds descriptive actual endpoint/count/time/unit differences to the care tool's
summary, including both BP values. It makes no clinical trend, target or causal claim.
Rollback is the isolated knowledge wiring/tool and trend-renderer patch; no DB
rollback or historical record modification is needed.
