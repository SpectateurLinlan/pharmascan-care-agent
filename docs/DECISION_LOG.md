# Decision Log — Claude business lifecycle vs earlier PharmaScan Agent workflow

| Decision | Kept from Claude A–D | Kept from older Workflow HTML | Reconciled final design / why |
|---|---|---|---|
| Business narrative | Phase A source → Phase B gallery → Phase C every dose → Phase D update | six technical flow views | A–D user story; the six flows are technical components, not mandatory sequential stages |
| Doctor/health-system actor | mock EHR feed can illustrate source | no Doctor Portal / real NEHR | patient uploads label/PDF/manual; mock feed only synthetic demo, not claimed live; external clinician exists but not authenticated app actor |
| Catalogue image seeded gallery | helpful shortcut to show candidate pictures | patient gallery embeddings and product-specific identity | `catalogue_seeded_candidate` reference, **not** patient identity ground truth; not mandatory if endpoint/data licence not ready |
| Personal photos | 3–5 per side if available | separate loose-pill encoder and package modality | optional photos, do not force opening blister; Stage2 matches cropped loose pills only until validated |
| Safety placement | Stage 3 screen/check embedded in vision server | app deterministic safety gate | do not physically force Stage2 rewrite; wrap existing safety API and put authoritative schedule/history checks in app backend |
| Daily dose | reminder → obligatory scan → speak | on-demand vision + no-photo self-report | Smart Check default, Always Suggest / Reminders Only optional; no photo needed to report intake; vision ≠ ingestion |
| Unknown/mismatch | ambiguous→retake/catalogue | explain measured reason, switch tools, abstain | tool-derived flags only, unknown even if similarity 0.99, no hallucinated photo cause |
| Historical stopped meds | remove from active gallery | preserve Active/Historical reference and regimen | keep records under retention; remove *eligibility for active checking* but retain historical products/photos |
| SaMD and DDI | optional red warning / notify doctor | potential regulated SaMD, no fake escalation | scope-limited advisory findings, patient/caregiver with consent, HSA assessment before real deployment |
| Model change | Claude highlighted re-embedding incompatible vectors | encoder_name/version/image_type | explicit `embedding_space_id` + preprocessing compatibility, re-embed consented originals on model change |
| Stage1 location | scanner stand-in finder | detected user bug 1 pill → 2 boxes | Stage1 regression is P0 for count-based verification; single-pill controlled crop fallback; multi-pill detector validation P1 |
| Language/voice | stage4 speak | voice-first PWA + text fallback | Tencent ASR/TTS optional; no unsafe dependency preventing text/voice fallback |
| Long-term care | regimen updates + history | full six Challenge 2 capabilities | add health observations, preventive tasks, preparation summary, adherence barriers; not only refill or reminders |
| ADP | vendor tool suggestion | own FastAPI Orchestrator | no ADP for MVP; WorkBuddy for developer assistance and evidence |

**Important:** The prior interactive HTML (`docs/reference/...`) is preserved as a technical snapshot because another owner is already using its API endpoint proposals. Changes described here are client/back-end contracts and *negotiation points*, not instructions to delete/rename the vision owner's routes.
