# External PharmaScan Stage2, Main Backend and Agent Tool Contracts

**Current integration candidate: v0.8.0 (2026-10-13).** Owner-supplied snapshot: `docs/external/pharmascan-api-openapi-0.8.0.json`; preserved actual historical snapshot: `docs/external/pharmascan-api-openapi-0.4.0.json` (recovered byte-for-byte from local Git HEAD, not regenerated). The v0.8.0 snapshot is frozen for local validation, not a promise that all deployed POST behavior or model performance is verified. Historical designs below do not override section G. Live GET /health and /v1/model-info were checked; image POST behavior remains SCHEMA-VERIFIED / LIVE-UNVERIFIED.

## A. Prior external endpoints vs app-level ownership (historical table; see current v0.8.0 section G)

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

## G. Verified v0.8.0 adapter contract (2026-10-13)

Evidence: `outputs/stage2_contract_audit.json` covers all 17 operations and 51 component schemas; `tests/fixtures/stage2/v0_8_0/manifest.json` labels all 12 synthetic payloads **SCHEMA_FIXTURE**, not LIVE. `live_manifest.json` and `outputs/stage2_live_smoke.json` separately record GET timestamps/status/content-type/hashes.

| Endpoint | Frozen response / application handling |
|---|---|
| GET /health | Health: ready + version + component status; live HTTP 200/schema valid |
| GET /v1/model-info | ModelInfo required metadata, calibration/imprint opaque objects; live HTTP 200/schema valid |
| GET /v1/tools | 200 schema remains `{}`; audit only, NEVER populate trusted tool registry from it |
| POST /v1/embed | multipart **image**, not file; embedding + **dim**, model_version, embedding_space_id, preprocess_version, normalized, framed_by, visual evidence; optional imprint_reads and text_reading |
| POST /v1/match | results[], each decision/medication_id/name/**similarity/closest/runner_up/message**; response threshold, margin, model/space, evidence, limits. Requests send both model_version and embedding_space_id |
| POST /v1/detect | boxes are **pixel [x0,y0,x1,y1]**, box_flags, pill_count, count_reliable, flags, found_by; no per-box score declared |
| POST /v1/identify | multipart **images** array (single-photo public Port sends one part), NOT image; top_k schema 1–20, current app deliberately caps at 10. Candidates with similarity, dose_form, strength/ingredients/RxNorm/product metadata; optional conditional confidence not exposed as pill identity |
| POST /v1/scan | nested detection, pills, optional dose/input_check, text_reading, evidence/limits; diagnostics ONLY. ScanPill adds unknown fields without typed decision/candidate definitions; do not map them |
| POST /v1/read-label | candidates name/brand/ingredients/strength/rxcui/rxnorm_name/found_in; fields: DocumentFields; list_check optional; provider source photo/pdf_text/pdf_scan. Schema accepts PDF but current transport only validated PNG/JPEG |
| GET /v1/pills/search, /v1/pills/{pill_id} | SearchResponse/Product; audit only, no new patient flow |
| POST /v1/safety/medications, /v1/safety/dose; GET /v1/safety/label | MedicationsResponse/DoseResponse/LabelResponse; audit only, advisory evidence never substitutes for independent app Safety Gate |
| POST /v1/feedback, DELETE /v1/feedback/{consent_id} | FeedbackStored/FeedbackDeleted; recorded only, NOT invoked/integrated |

**Dimension caveat:** schema types embedding as number[], with no minItems/maxItems enforcing 256. The endpoint description and live ModelInfo declare 256; adapter additionally verifies actual length, dim, finite numeric values and declared normalization (norm tolerance 1e-3 is numeric consistency, NOT a clinical threshold). Missing required metadata fails, never falls back to configured values.

**Public boundary:** `app.contracts.vision.VisionPort` and DTOs; legacy infrastructure/vision_contracts is compatibility re-export only. match accepts one **EmbeddingResult** query with model/space/preprocessing metadata plus GalleryReference metadata; multi-query rejected rather than silently truncating. `HttpStage2VisionProvider` validates frozen OpenAPI before projecting wire fields. Unexpected allowed fields are ignored; required fields and invalid typed fields fail closed. Similarity is raw cosine, NOT probability; threshold/margin are declarations, not independently calibrated metrics; threshold_version remains unknown.

**Source boundary:** `app.contracts.source_extraction.SourceExtractionPort` → `PharmaScanLabelProvider`. Product identity and RegimenEvidence are separate. Preserve every Printed.value/line including dose_form, directions, quantity, date, expiry_date; null and omission both mean missing (explicit null tracked). Quantity is amount dispensed, not per-dose quantity; date is not an inferred start/stop date. No parsing printed directions into dose/frequency/times/duration, no direct activation or repositories. `/api/medication-sources/extract` remains a subsequent authenticated integration task; the new Port/provider is not yet wired into the patient HTTP flow.

**Transport:** injected httpx client/config/schema/sleeper, HTTPS/no redirects, bounded response size/timeouts, PNG/JPEG content decode/pixel cap/EXIF stripping. GET network/5xx retries at most two with bounded exponential backoff; POST never auto-retried. 4xx, 5xx/network and malformed/HTML/schema errors are distinct explicit failure types. PDF uses manual fallback until a validated PDF transport exists.

**Live coverage:** GET only, no auth, no patient data or image upload. Image POST, catalogue/knowledge calls and feedback not exercised. Schema conformance does not validate model accuracy, deployed detector fixes, OCR completeness, FAR/FRR or clinical safety; V003 remains incomplete.
