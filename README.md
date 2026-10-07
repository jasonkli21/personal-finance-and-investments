# Portfolio Intelligence

A personal finance and investment analysis application for maintaining a reviewed, auditable view of accounts, positions, valuation, ETF exposure, transactions, historical performance, tax lots, portfolio planning, and source-linked research.

The project favors deterministic finance calculations and explicit source provenance over opaque automation. AI capabilities are integrated behind a separate boundary and do not own canonical portfolio data.

## What it does

Core capabilities include:

- reviewed account and position imports;
- fund/ETF holdings ingestion and exposure reconciliation;
- dated owned-portfolio valuation;
- historical portfolio performance;
- bank/card transaction imports;
- finance summaries;
- tax-lot storage and inspection;
- hypothetical sale planning;
- allocation and liquidity planning;
- immutable/revisioned portfolio snapshots;
- source-linked manual research workspaces;
- frozen reports and export artifacts;
- brokerage PDF text-layer processing;
- private file storage with bounded job execution;
- synthetic offline demo data;
- encrypted recovery tooling.

The application is designed to work locally with PostgreSQL and no market-data, bank, model, or other provider credentials after dependencies and optional demo fixtures are installed.

## Design principles

- **Finance data remains authoritative in this application.**
- **Calculations and validations are deterministic.**
- **Imports are reviewed rather than blindly trusted.**
- **Provenance is preserved for positions, quotes, fund data, and research.**
- **Private files stay outside the public web surface.**
- **Schema changes and recovery workflows are explicit.**
- **AI is optional and cannot replace finance-domain invariants.**

## Architecture

```text
                       Browser
                          |
                          v
                 React / Vite web app
                          |
                          v
                 +-------------------+
                 | FastAPI finance   |
                 | API               |
                 |                   |
                 | imports           |
                 | valuation         |
                 | planning          |
                 | research          |
                 | jobs / auth       |
                 +----+---------+----+
                      |         |
                      |         +---- optional typed boundary
                      |                    |
                      v                    v
                 PostgreSQL         personal-ai-system

Private files
     |
     v
local private volume
or private GCS in cloud
```

Hosted infrastructure uses Cloud Run/Cloud Run Jobs, Neon Postgres, private GCS, Secret Manager, and Firebase Hosting.

For the current delivery boundary and open gates, see [current state](docs/current-state.md). The [documentation router](docs/README.md) identifies authoritative sources and the smallest reading set for each task.

## Repository layout

```text
.
├── apps/
│   └── web/                    # React/Vite frontend
├── services/
│   └── api/
│       ├── app/                # FastAPI finance domain
│       └── tests/
├── tests/
│   └── infra/                  # infrastructure policy/config checks
├── fixtures/
│   └── stage-0/                # synthetic demo data
├── infra/
│   └── terraform/              # GCP/Neon deployment assets
├── docs/
│   ├── README.md               # context router and source authority
│   ├── current-state.md        # concise implementation status and open gates
│   ├── 01-product-spec.md
│   ├── 02-architecture.md
│   ├── 03-data-sources.md
│   ├── 04-ingestion-and-ai.md
│   ├── 05-roadmap.md
│   ├── adr/                    # accepted durable decisions
│   ├── history/                # superseded provider context and handoffs
│   ├── 06-security-and-deployment.md
│   └── 07-postgres-neon.md
├── compose.yaml
└── package.json
```

## Tech stack

### Web

- React
- TypeScript
- Vite
- pnpm 11.19.0

### API

- Python 3.12
- FastAPI
- SQLAlchemy / Alembic
- PostgreSQL / psycopg
- `uv`

### Local / cloud data

- PostgreSQL 16 locally
- Neon Postgres in cloud
- local private file volume in development
- private GCS in cloud

### Cloud

- Google Cloud Run
- Cloud Run Jobs
- Firebase Hosting
- Secret Manager
- Artifact Registry
- Terraform

## Local setup

### Prerequisites

- Docker with Compose
- Node.js 22.12+, 24, or newer supported versions
- pnpm 11.19.0
- Python 3.12
- `uv`

### 1. Clone and configure

```bash
git clone https://github.com/jasonkli21/personal-finance-and-investments.git
cd personal-finance-and-investments

cp .env.example .env
```

The example environment is for loopback/local development.

### 2. Start the database and API containers

```bash
docker compose up --build -d
```

### 3. Apply migrations

```bash
uv run --directory services/api --locked alembic upgrade head
```

### 4. Install frontend dependencies

```bash
corepack enable
corepack prepare pnpm@11.19.0 --activate
pnpm install --frozen-lockfile
```

### 5. Start the web app

```bash
pnpm dev:web
```

Open:

```text
http://127.0.0.1:5173
```

### 6. Check service readiness

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/ready
```

`/health` checks process liveness.

`/health/ready` performs a database readiness check.

## Synthetic offline demo

Demo data is opt-in and never seeded automatically.

Set:

```env
DEMO_MODE=true
```

Then:

```bash
docker compose up --build -d
uv run --directory services/api --locked alembic upgrade head
uv run --directory services/api --locked python -m app.demo_seed
```

The demo uses fictional synthetic accounts, securities, ETF holdings, cash, and prices.

To remove only labelled demo data:

```bash
DEMO_MODE=true \
  uv run --directory services/api --locked \
  python -m app.demo_seed --reset-demo
```

The reset command refuses destructive cleanup when demo entities have been reused or modified by non-demo data.

## API contract generation

After route/schema changes:

```bash
pnpm api:generate
```

Generated OpenAPI and TypeScript contract artifacts are checked for drift by the main quality command.

## Quality checks

Install dependencies, then run:

```bash
uv sync --directory services/api --locked
pnpm check
```

`pnpm check` runs:

- generated API drift checks;
- ESLint;
- Ruff linting;
- Prettier/Ruff format checks;
- TypeScript;
- mypy;
- Vitest;
- infrastructure guardrails;
- pytest;
- production web build.

Browser journeys run separately:

```bash
pnpm test:e2e
```

E2E and destructive database tests require explicit disposable-database opt-in.

## Database configuration

Local development can use the discrete `POSTGRES_*` settings in `.env`.

An explicit `DATABASE_URL` overrides them.

Cloud runtime expects a pooled Neon URL:

```env
DATABASE_URL=postgresql+psycopg://...?...sslmode=verify-full&sslrootcert=system
```

Schema migration can use a separate direct endpoint:

```env
MIGRATION_DATABASE_URL=postgresql+psycopg://...
```

Do not give migration credentials to the ordinary runtime.

## Private files and jobs

Local Compose mounts a private application directory under:

```text
/app/.private
```

The container runs this storage as a dedicated non-root UID/GID.

Import and job execution are bounded by server-side limits such as:

```env
MAX_PRIVATE_FILE_BYTES=20000000
MAX_IMPORT_FILE_BYTES=5000000
MAX_IMPORT_ROWS=5000
MAX_PDF_PAGES=40
JOB_LEASE_SECONDS=30
JOB_MAX_ATTEMPTS=3
```

## AI integration

Finance remains authoritative for:

- portfolio data;
- calculations;
- validations;
- workflow state;
- planning results;
- user-facing finance UI.

Reusable AI capabilities integrate through `personal-ai-system`.

The integration is intentionally optional and disabled by default:

```env
PERSONAL_AI_ENABLED=false
```

Do not enable it until the upstream contract and data-handling/authentication boundary are configured.

## Cloud deployment

The prepared target architecture is:

```text
                       Firebase Hosting
                              |
                         /api proxy
                              |
                              v
                     Cloud Run finance API
                         |           |
                         |           +-----> private GCS
                         |
                         +-----> Neon Postgres

                  Cloud Run Job
                       |
                       +---- bounded background work
```

Infrastructure is defined under:

```text
infra/terraform/
```

No cloud resources are created by merely cloning or running the local stack.

### Cloud prerequisites

Prepare:

1. a dedicated GCP project;
2. a Neon project/database;
3. Firebase Hosting;
4. Artifact Registry;
5. Secret Manager entries;
6. OIDC identity configuration;
7. a private GCS bucket;
8. approved billing/retention settings.

Neon database creation/roles are operator-managed outside Terraform.

### Terraform setup

```bash
cd infra/terraform

cp terraform.tfvars.example terraform.tfvars
```

Fill the ignored local variable file with approved deployment identifiers.

Bootstrap with the runtime disabled, then review:

```bash
terraform init
terraform fmt -check
terraform validate
terraform test
terraform plan
```

Review a saved plan before applying.

Secret payloads are not stored in Terraform state/configuration.

### Secrets and database roles

Create Secret Manager versions for:

- pooled runtime `DATABASE_URL`;
- OIDC client secret;
- application session signing key.

Keep `MIGRATION_DATABASE_URL` as an operator/release credential rather than a runtime secret.

### Image deployment

Build/push the exact-source API image, resolve it to an immutable SHA-256 digest, then configure:

- `api_image_digest`;
- numeric Secret Manager versions;
- `enable_runtime=true`.

Run Alembic with the direct Neon migration credential before promoting the reviewed runtime plan.

### Firebase Hosting

After Terraform outputs are available:

```bash
terraform output -json firebase_config > firebase.json

pnpm --dir ../.. build:web

firebase deploy \
  --project <actual-project> \
  --config firebase.json \
  --only hosting
```

The generated Firebase configuration is ignored by Git.

## Authentication and security

Local development keeps browser sessions disabled.

Hosted mode uses OIDC/PKCE with server-managed sessions.

Important boundaries:

- finance routes are protected by backend authorization;
- database/runtime and migration credentials are separated;
- private GCS is not publicly readable;
- Cloud Run service access is still protected by application authorization;
- API request logging is redacted;
- database URLs and session secrets belong in Secret Manager;
- demo/local credentials are never suitable for a public deployment.

## Recovery

The repository includes encrypted portable recovery tooling and database/private-storage recovery tests.

Before trusting a hosted deployment with personal finance data, run the documented synthetic recovery and private-object checks against the actual target environment.

## Documentation

Useful starting points:

```text
docs/01-product-spec.md
docs/02-architecture.md
docs/03-data-sources.md
docs/04-ingestion-and-ai.md
docs/06-security-and-deployment.md
docs/07-postgres-neon.md
docs/gcp-neon-migration.md
infra/terraform/README.md
```

## License

No license is currently specified. Add an explicit `LICENSE` file before treating the repository as generally reusable open-source software.
