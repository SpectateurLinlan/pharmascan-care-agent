# Third-party components and external services

The project's Apache-2.0 license covers project-owned source. It does not replace dependency licenses or authorize use of external services/data. Installed package metadata was inspected for the versions below; lockfiles and environment versions can differ. Retain package license notices when redistributing dependencies/bundles. This table is not a complete transitive software bill of materials.

| Component | Inspected version | Declared license |
|---|---|---|
| React / React DOM | 18.3.1 | MIT |
| Supabase Auth JS | 2.109.0 | MIT |
| Vite | 7.3.7 | MIT |
| TypeScript | 5.9.3 | Apache-2.0 |
| Playwright | 1.64.0 | Apache-2.0 |
| FastAPI | 0.143.0 | MIT |
| Pydantic | 2.14.1 | MIT |
| Uvicorn | 0.54.0 | BSD-3-Clause |
| HTTPX | 0.28.1 | BSD-3-Clause |
| jsonschema | 4.26.0 | MIT |
| Pillow | 12.3.0 | MIT-CMU |
| Google GenAI SDK | 2.30.1 | Apache-2.0 |
| Psycopg | 3.3.6 | LGPL-3.0-only |
| pywebpush (optional) | 2.5.0 | MPL-2.0 |
| icalendar (test/export validation) | 7.3.0 | BSD-2-Clause |

SVG interface icons are authored project geometry; no icon font or raster photo set was added for the redesign. Synthetic Stage2 JSON fixtures and frozen contracts remain required for reproducible adapter tests; they are not patient photos or a redistributed training dataset.

## External services and data

- Supabase, Gemini, optional Tencent speech and Stage2 are independently operated services. Access, privacy, quotas, regions and billing follow their respective terms; credentials confer no project-wide dataset rights.
- Stage2 API v0.10.0 declares DDInter 2.0 under **CC BY-NC-SA 4.0**. Noncommercial/share-alike restrictions require separate review for a proposed commercial use. This app does not enable a comprehensive interaction checker or claim commercial medical-data licensing.
- Stage2's catalogue is not a comprehensive Singapore product database. Catalogue access does not authorize seeding patient references or retraining. See the frozen [provider contract](../external/pharmascan-api-openapi-0.10.0.json) and [integration notes](../STAGE2_V010_UPGRADE.md).
- No MOH/HealthHub content has been scraped, embedded or relicensed. Feedback/training endpoints are not used for ordinary gallery uploads.
- General medication education retrieves bounded openFDA/SPL label excerpts with source Set ID, version and update metadata. US label coverage is partial and is not Singapore registration or personal prescribing authority. Third-party label content retains any applicable rights; no complete drug reference is redistributed. See [knowledge-source policy](../MEDICATION_KNOWLEDGE_SOURCES.md), [openFDA terms](https://open.fda.gov/terms/) and [label API](https://open.fda.gov/apis/drug/label/).

Before distributing a packaged release, inspect its complete dependency tree and ship the applicable upstream notices. Project licensing does not establish clinical/regulatory approval.
