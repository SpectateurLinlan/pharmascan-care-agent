# MediThread — Healthcare Challenge 2

*A Personalised Medication & Long-Term Self-Care Agent*

The implementation centres all six capabilities on medication management. The
medication-related preventive scope is this project's product choice, not a claim
that the official challenge only requires these subscenarios.

| Capability | Patient workflow | Current verification |
| --- | --- | --- |
| Medication Understanding | Ask about general uses with matched openFDA label provenance; separately ask how to follow a current reviewed personal regimen. Unmatched products and unknown personal indications remain uncertain. | Deterministic provider/tool/safety tests and bounded real openFDA smoke passed. This RC's live Gemini request timed out; successful hosted function calling is not verified. |
| Medication Management | Add evidence or manual instructions, review, explicitly confirm, activate; retain current/past plans and stock/refill history. | Native React enrollment through local Application API/B14 passed. Existing migration 025 live concurrency/RLS evidence remains applicable; not rerun or reapplied. |
| Adherence Support | Report taken/not taken/unsure, record difficulties and choose follow-up actions. Missing reports stay unrecorded. | Local policy, API, idempotency, barrier and cross-session tests passed. Hosted browser acceptance remains pending. |
| Health Tracking | Record medication-related measurements/symptoms; explain sampled changes with dates, units and observation counts. | Cross-day descriptive interpretation and EN/ZH tests passed. No causal or diagnostic conclusions are asserted. |
| Preventive Health (medication-related) | Review supply, medication reviews, symptom/adherence follow-up and patient-reported treatment monitoring requirements. | Confirmed task creation, status transitions and new-session retrieval tested locally. Push device delivery remains unverified. |
| Healthcare Preparation | Review/export a summary of current/past plans, reported doses, observations, barriers, stock issues and open questions. | Five-day scenario built through Application HTTP APIs and independent B14 confirmations; source-backed summary tests passed. |

## Agent workflow

Patient intent → bounded Gemini orchestration → allowlisted typed tool → authorised
application service → deterministic validation → explicit confirmation when required
→ persistence → follow-up. Model/provider failures use an identified fallback, never
fabricated provider success. Clinical facts are queried from owned records; optional
conversation history is not authoritative medication memory.

## Internal demonstration scenarios

These are project acceptance scenarios, not six mandatory official competition demos.

| Scenario | Evidence and limits |
| --- | --- |
| A — Enrollment | Current React manual-entry → native draft payload → review → B14 → activation passes against isolated local persistence. Source reconciliation/conflict guards have backend regression coverage. Current hosted OCR and PDF ingestion are not established by this run. |
| B — Visual check | Gallery ownership, compatible embeddings and regimen reconciliation have local contract coverage. Prior external evidence is distinct from current hosted UI acceptance; no identification accuracy or safe-to-take claim. |
| C — Mismatch/unknown | Safety-policy and tool tests retain the existing plan, clarify conflicts and abstain. No automatic caregiver notification is assumed. |
| D — Long-term review | Five scheduled days, two reported taken, one reported not taken, one unsure and one unrecorded; observations, barriers, inventory/refill and open care tasks. Public APIs/B14 create records; not direct insertion of final outcomes. |
| E — Supply/barrier | Confirmed stock count → refill review task → confirmed refill transaction → updated inventory/task → new-session retrieval; local idempotency, units, PRN and stopped-plan negatives. |
| F — Follow-up | Patient-related request → clarification → explicit task confirmation → observation → new-session read → completion/deferral/cancellation; local API/tool tests. |

## Evidence locations

- [Native browser journey](../frontend/e2e/medithread-rc.spec.ts)
- [Cross-day review via HTTP/B14](../tests/backend/test_release_scenarios.py)
- [Knowledge, personal instructions and interpretation](../tests/backend/test_medication_understanding.py)
- [Inventory, barriers and care tasks](../tests/backend/test_long_term_care.py)
- [Opt-in real conversation persistence](../tests/backend/test_session045_live.py)
- [Opt-in openFDA smoke](../tests/backend/test_openfda_live.py)
- [Opt-in migration 025 acceptance](../tests/backend/test_regimen_overlap_live.py)

Mock/local tests establish deterministic behaviour, not external model quality or
production availability. External tests remain opt-in. No new migration, production
deployment or Web Push delivery was performed for this RC. See the
[deployment checklist](DEPLOYMENT_CHECKLIST.md) and [limitations](DEVELOPMENT.md#product-behaviour--data-notes).
