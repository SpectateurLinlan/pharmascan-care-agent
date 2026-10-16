# MediThread — Project Structure

> Public source is organised by component responsibility. The repository name
> remains `pharmascan-care-agent`; the patient-facing product is MediThread.

[Product overview](../README.md) · [Development guide](DEVELOPMENT.md) · [Architecture](ARCHITECTURE.md) · [Deployment](../deploy/README.md)

---

## 1. Repository Root

```text
pharmascan-care-agent/
├── README.md          # Product overview, capabilities, screenshots and limits
├── LICENSE            # Apache-2.0 project source licence
├── NOTICE             # Attribution and third-party licence boundary
├── DESIGN.md          # Patient UI design conventions
├── .env.example       # Backend configuration template; no real credentials
├── .gitignore         # Generated artifacts and sensitive-file exclusions
├── .python-version    # Hosted Python version selection
├── pyproject.toml     # Python dependencies, test/lint configuration, worker entry
├── vercel.json        # Independent Push Dispatcher project only
└── .vercelignore      # Worker deployment upload exclusions
```

---

## 2. Backend

```text
backend/
├── MEDICATION_UNDERSTANDING.md  # Knowledge tool interface and frontend handoff
└── app/
    ├── config.py              # Explicit runtime configuration
    ├── contracts/             # Public typed DTOs, protocols and status enums
    ├── domain/                # Pure safety, dose-display and inventory rules
    ├── application/           # Enrollment, dosing, knowledge, care and reminders
    ├── agent/                 # Bounded orchestration and allowlisted typed tools
    ├── infrastructure/        # Supabase, provider and persistence adapters
    └── transport/
        ├── app_factory.py     # Patient HTTP application factory
        ├── container.py       # Patient service composition and dependency injection
        ├── routes/            # Authenticated public patient API routes
        ├── dispatcher.py      # Protected worker HTTP application
        └── worker_container.py # Separate privileged worker composition
```

Business services enforce ownership, reviewed evidence and confirmation. The Agent
does not access database tables or bypass deterministic safety checks.

---

## 3. Frontend

```text
frontend/
├── README.md              # Patient UI development notes
├── .env.example           # Public Auth configuration template
├── package.json           # Cross-platform dependencies and npm scripts
├── package-lock.json      # Reproducible dependency graph, including native variants
├── index.html             # MediThread title and social metadata
├── vite.config.ts         # Vite build and local API proxy
├── public/
│   ├── icon.svg           # MediThread application icon
│   ├── manifest.webmanifest # PWA identity and installation metadata
│   └── sw.js              # Notification handling; no patient-data cache
├── src/
│   ├── App.tsx            # Four destinations and in-place Assistant integration
│   ├── api/               # Typed public HTTP clients and identity-only Auth adapter
│   ├── components/        # Patient workflows, forms and confirmation surfaces
│   ├── ui/                # Shared tokens, layout and presentation primitives
│   ├── language.tsx       # Language and preference context
│   └── webPush.ts         # Explicit current-device subscription operations
└── e2e/                   # Opt-in browser journeys and synthetic test surfaces
```

The four primary destinations remain **Today / Medicines / Records / Me**.
Patient business data goes through FastAPI, not direct frontend table access.

---

## 4. Persistence & Tests

```text
supabase/
├── migrations/            # Ordered SQL migrations, including patient RLS
└── rollback/              # Reviewed rollback scripts with data-loss guards

tests/
├── backend/               # Domain, application, HTTP, provider and opt-in Live tests
└── fixtures/
    └── stage2/            # Required synthetic payloads and versioned contract cases
```

An already-applied migration must not be edited or replayed merely for deployment.
Synthetic fixtures are not visual accuracy or clinical-validation evidence.

---

## 5. Deployment & Operator Scripts

```text
deploy/
├── README.md              # Service roots, build commands and isolation rules
├── frontend/
│   └── vercel.json.example # Routing template; requires actual patient API hostname
├── render/
│   └── render.yaml        # Patient API Blueprint; repository-root service
└── dispatcher/
    └── index.py           # Independent Vercel Python Push Dispatcher

scripts/
├── start_dev.py           # Local frontend/backend launcher
├── run_patient_api.py     # Production-profile patient API startup/resource checks
├── run_reminders.py       # Bounded existing notification worker / local CLI
├── create_vapid_keys.py   # Operator-invoked key utility; never run implicitly
├── db.py                  # Migration status, application and verification utility
└── stage2_contract_diff.py # Frozen external contract comparison utility
```

The Vercel frontend root is `frontend`. Render and the separate Vercel Dispatcher
use the repository root with different entrypoints and environment variables.
Worker privileges must not be shared with the patient API or browser bundle.

---

## 6. Public Documentation

| File / directory | Purpose |
| --- | --- |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Local setup, configuration, running and testing |
| [CHALLENGE2.md](CHALLENGE2.md) | Six capabilities, Agent workflows and verification limits |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Components, dependencies and trust boundaries |
| [API_CONTRACTS.md](API_CONTRACTS.md) | Patient and external provider interfaces |
| [DATA_MODEL.md](DATA_MODEL.md) | Patient records and persistence boundaries |
| [SAFETY_AND_EVALUATION.md](SAFETY_AND_EVALUATION.md) | Safety invariants and evidence interpretation |
| [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md) | Hosting and post-deployment smoke checks |
| [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md) | Patient API build/start/environment instructions |
| [REMINDERS.md](REMINDERS.md) | Reminder, queue, Web Push and device requirements |
| [LONG_TERM_CARE.md](LONG_TERM_CARE.md) | Inventory, barriers, observations and follow-up interfaces |
| [external/](external/) | Frozen external API contracts required by adapters |
| [images/](images/) | Approved genuine synthetic-data product screenshots |
| [legal/](legal/) | Third-party notices and reuse boundaries |

---

Real environment files, credentials, patient uploads, tool instructions and private
development evidence are not part of this public project structure.
