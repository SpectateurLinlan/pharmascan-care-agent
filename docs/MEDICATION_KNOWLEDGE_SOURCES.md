# Medication knowledge sources ? P1/P2 research

Date:2026-10-15. No knowledge/RAG/DDI tool is enabled by this research. Patient-specific schedule remains structured reviewed regimen data.

| Primary source | API / coverage | Licence / reuse boundary | Current decision |
|---|---|---|---|
| [HSA Infosearch](https://www.hsa.gov.sg/e-services/infosearch/) | Singapore therapeutic-product registration search. Public search availability does not establish an API contract. | API access, bulk reuse and commercial licence NOT VERIFIED. Product classification is not patient instruction. | P1: clarify access/terms and exact Singapore product mapping before integration. |
| [DailyMed REST service](https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm) | Official versioned SPL label lookup/history, JSON/XML; US label coverage. | API exists; per-content/media reuse and commercial applicability require review. US product mapping is not Singapore coverage. | P1/P2: possible cited label tool, not comprehensive DDI checker. |
| [MedlinePlus web service](https://medlineplus.gov/about/developers/webservices/) | Health-topic retrieval and attribution, not a patient-medication schedule or pairwise interaction API. | [Content policy](https://medlineplus.gov/about/using/usingcontent/) distinguishes government and licensed/vendor content. Do not assume all drug/illustration content is freely reusable. | P2: narrowly attributed patient information after licensing/coverage review. |
| [DDInter terms](https://ddinter.scbdd.com/terms/) | Drug-interaction dataset; product/ingredient/market coverage must be established. | CC BY-NC-SA4.0; commercial use permission is unresolved. | Not integrated. Obtain appropriate licensed DDI data/permission before any interaction screening claim. |

Future get_medication_knowledge must carry source/version/citation/product-market coverage. A document RAG is not a validated interaction checker. No alert is not evidence of safety; Gemini must not invent dose adjustments or infer diagnoses. Until a licensed validated tool exists, retain source evidence and recommend pharmacist/doctor verification for unresolved interactions or doses.

## 0.10.0 bounded service evaluation (2026-10-15)

REAL LIVE /v1/safety/medications returned a typed coverage response with unscreened inputs and uncheckable pairs. An intentionally unknown synthetic product was nevertheless resolved to an ingredient with all_identified=true. Patient screening therefore stays disabled. [DDInter2.0 official terms](https://ddinter2.scbdd.com/terms/) were checked and state CC BY-NC-SA4.0; commercial permission remains unresolved. [openFDA label documentation](https://open.fda.gov/apis/drug/label/) describes US manufacturer/distributor-submitted SPL data with responsible-use limitations. /safety/label is not a Singapore patient instruction source and is not enabled. No general knowledge/interaction tool was added to Gemini.
