# External PharmaScan Stage2, Main Backend and Agent Tool Contracts

**Version:** hand-off 2026-10-13. The Stage2 teammate is actively updating the real API; preserve compatibility with `docs/reference/PharmaScan_Care_Agent_Workflow_2026-10-12.html` until jointly agreed versioned changes. The OpenAPI v0.4.0 is an **older documented contract**, not a guarantee of latest behavior.

## A. Prior external endpoints vs app-level ownership

| Route (external) | Supported claim from earlier OpenAPI | App decision | Owner / blocker | Priority |
|---|---|---|---|---|
| `GET /health` | Health check | keep | vision owner; cold start tests | P0 |
| `POST /v1/embed` | cropped pill → 256-d vector | keep; validate dimension & metadata; image via backend | vision owner; real JSON needed | P0 |
| `POST /v1/match` | query vectors + caller-supplied gallery | keep Hackathon; app owns persistent refs | vision owner + app adapter | P0 |
| `POST /v1/identify` | US catalogue ranked visual matches, optional imprint/shape/colour | keep, **candidate only** | vision owner | P0 |
| `POST /v1/scan` | convenience multi-pill scan / stand-in finder | use **diagnostics** only until tested; known single-pill duplicate boxes | vision owner | P0 |
| `GET /v1/pills/search` | US pill catalogue query | keep if product mapping confirmed | vision owner | P1 |
| `GET /v1/pills/{pill_id}` | catalogue product details | keep; market caveat | vision owner | P1 |
| `GET /v1/pills/{pill_id}/image/{n}` | catalogue reference images | keep as non-authoritative image; check permitted usage | vision owner | P1 |
| `POST /v1/safety/medications` | ingredient duplication / advisory DDI | adapter now; future safety service boundary; no full-safety claim | app; license check | P1 |
| `POST /v1/safety/dose` | compare supplied counts vs schedule | legacy diagnostic only; **move authoritative rules to main app service** | app | P0 |
| `/v1/safety/label` | US labeling lookup | wrap as knowledge retrieval only, source citation | app | P1 |
| `POST /v1/feedback` / delete | consent feedback flow | keep **out of MVP** or explicit opt-in queue, not gallery persistence | vision owner | P2 |
| `GET /v1/model-info` | **proposed; not confirmed** | expose `embedding_space_id`, weights/preprocess, limits, calibration version | vision owner | P0 |
| `POST /v1/detect` | **proposed; not confirmed** | optional validated detection + NMS/quality flags | vision owner | P1 |
| `POST /v1/search-by-embedding` | **proposed; not confirmed** | avoid duplicate inferencing, evaluate after freeze | vision owner | P2 |
| `/v1/read-label` | older Claude HTML may label available, previous OpenAPI **did not verify** | OCR belongs to app; do not assume API route exists | app | P1 |

**KEEP external API separate from main application APIs.** Distinguish `GET /v1/pills/{id}` catalogue from `GET /api/patients/me/medications` patient medical records. The user has already sent prior API endpoint proposals to vision owner: changes require a new version + migration announcement, never silent deletion.

## B. Suggested typed adapter DTOs (application facing; NOT claims of exact external JSON)

```python
class EmbedInputDTO:
    image_reference: str       # validated private image/crop ref
    modality: Literal['loose_pill']
    crop_contract: str         # versioned preprocessing requirements

class EmbedResultDTO:
    embedding: list[float]     # checked finite, expected 256 only if actual API verified
    embedding_space_id: str
    model_version: str
    preprocessing_version: str
    normalized: bool | None
    provider_request_id: str | None

class GalleryReferenceDTO:
    reference_set_id: UUID
    patient_medication_id: UUID
    product_id: UUID | None
    embedding_space_id: str
    embeddings: list[list[float]]

class MatchResultDTO:
    decision: Literal['visually_consistent','ambiguous','unmatched','unavailable']
    best_reference_set_id: UUID | None
    score: float | None   # VISUAL similarity, NEVER probability
    margin: float | None
    threshold_version: str | None
    quality_flags: list[str]
    provenance: list[str]

class CatalogueCandidateDTO:
    external_catalogue_id: str
    display_name: str
    brand: str | None
    strength: str | None
    form: str | None
    market: str
    visual_similarity: float | None
    source_dataset: str
```

**Do not fabricate these fields as if the external API emits them.** Write an `ExternalPharmaScanAdapter` mapping real external JSON to these internal DTOs; absent fields remain unavailable/unknown. `ModelVersionMismatch`, `Timeout`, `UnsupportedModality`, `UpstreamSchemaError` each have explicit error pathways. Request contract should cap image and JSON size and redact patient identifiers from external model calls.

## C. Main FastAPI user-facing APIs (to implement)

| Route | Input → Output | Side-effect/policy |
|---|---|---|
| `POST /api/demo/start` | authenticated **anonymous** principal → isolated synthetic seed status | idempotent user-owned seed, rate limit; no shared account |
| `POST /api/agent/messages` | text + typed attachment refs + session_id → response/tool trace state | token verified, bounded steps, safe tool allowlist |
| `GET /api/me/medications` | JWT → patient active/history snapshot | patient-owned RLS |
| `POST /api/medications/drafts` | source/file/manual fields → pending draft | no plan activation without reviewed required inputs |
| `POST /api/medications/drafts/{id}/confirm` | reviewed field IDs, origin evidence, explicit confirmation → regimen version | idempotent, scope and source check; historic preserved |
| `POST /api/medication-sources/extract` | PDF/image document id → extracted fields + provenance | OCR suggestions only, not prescriptions |
| `POST /api/reference-sets` | linked product + image modality + reviewed evidence → images + eligible embeddings | never place box/blister in loose-pill vector group |
| `POST /api/vision/check-dose` | specific due-dose id + image reference → advisory evidence/quality | patient plan check + no auto-take flag |
| `POST /api/doses/{occurrence_id}/report` | taken/not taken/unsure, timestamp, optional vision run → self report event | idempotent, no ingestion proof |
| `GET /api/me/dose-history` | date range → state-aware history | not_reported ≠ missed |
| `POST /api/health-observations` | measure type/value/unit/observed_at/source → record | no diagnosis or medication action |
| `GET /api/me/care-tasks` | tasks/next dates | distinguish user-added vs source-backed |
| `POST /api/reviews/summary` | selected time range → factual medicine/observation summary | requires user review before external sharing |
| `GET/PUT /api/me/preferences` | visual mode, language, accessibility, timezone | `SMART` default, per-patient |
| `POST /api/me/caregiver-contact` | email/phone, scope, consent intent → pending contact | external notification only after independent verification |

`POST /api/agent/messages` payload should include `client_turn_id` and `session_id`, to avoid duplicate tool actions under retried requests. Do not let the agent select arbitrary `patient_id`.

## D. Quality output codes (distinct from visual decision)

- `image_unusable` with flags (only measured) `blur`, `glare`, `too_dark`, `pill_too_small`, `crop_cutoff`, `duplicate_boxes`, `overlap`.
- `quality_unknown` if no validated image quality analyzer exists.
- `good_quality_but_unmatched` requires **both** a validated quality check and calibrated gallery decision.
- `ambiguous_candidates` when score margins insufficient.
- `outside_catalogue_coverage` when known US-only catalogue cannot resolve locally marketed drug.
- `upstream_unavailable` for service error; never map to `unmatched`.

## E. Tests and team-owner handoff (priority first)

1. P0 Contract: request one **real** successful and one failed JSON response for `/embed`, `/match`, `/identify` and `/scan`, including HTTP status, content-type, timeouts, response size, `model_version`/`embedding_space_id` if available; redact images/patient data. Keep them under `tests/fixtures/stage2/` with source/version.
2. P0 Vision: reproduce user TEVA single pill → two overlapping boxes; tests must reject duplicate count. Make sure /scan crop/box/identify logic is observable and not an implicit untestable blob.
3. P0 Embeddings: correct normalization, dimensionality, vector compatibility and threshold/margin on held-out same-product/different-product pairs; explicitly include IR/XR and same-shape different-strength ambiguity.
4. P0 Main App: gallery stored in private database; RLS prevents patient-A reading patient-B; no photo still produces only self-report; provider timeout must not be reported as match.
5. P1 Products: name+ingredient+strength+form+brand+manufacturer+market disambiguation; avoid automatic RxNorm US ↔ Singapore product equivalence.
6. P1 DDI: mapped vs unmapped ingredients and NC licensing; no alert does not mean safe.
7. P2 Feedback: consent and deletion/correction trace; do not use patient-labelled gallery training unless human-reviewed and allowed.

## F. Stage2 owner requested response (can paste to teammate)

> Please preserve existing v0.4.0 routes during our hackathon integration, but share latest actual JSON schemas and model metadata (encoder weights/preprocessing/normalization, embedding space, calibrated threshold/margin). Our app will persist personal gallery locally. We will call `/embed`, `/match`, `/identify` and only use `/scan` diagnostics until the single-pill double-box issue is fixed. Please confirm whether `/v1/model-info`, standalone detection/quality flags, and optional catalogue reference embeddings are feasible without breaking existing callers. Distinguish proposed from deployed routes and provide at least one reproducible success/failure payload for contract tests.
