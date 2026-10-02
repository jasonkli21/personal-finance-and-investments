# Portfolio Intelligence

Stage 1 delivers reviewed position/fund imports, dated owned valuation, reconciled one-level ETF exposure, issuer rollups, frozen reports, drill-down and CSV export. The first Stage 2 slice adds local text-layer brokerage PDF preview through the existing reviewed position-import flow; scanned PDFs, bank/card transactions, dashboards and background jobs remain pending. See [`docs/stage-2-release.md`](docs/stage-2-release.md) for its exact limits. The app works locally with PostgreSQL 16 and no provider keys. Production Aurora DSQL remains unverified.

Reusable AI capabilities will integrate through `personal-ai-system`; finance retains authoritative data, deterministic validation/calculations, workflows and UI. The current `PersonalAIClient` is a disabled extraction boundary with a synthetic fake, not a live integration. Leave `PERSONAL_AI_ENABLED=false`; true fails startup until an upstream contract and security/data-handling gates are implemented. See [ADR 0001](docs/adr/0001-shared-personal-ai.md). No AI service or model credentials are needed for local imports.

## Requirements

- Docker with Compose for PostgreSQL 16 and the API
- Node.js 24 (used in CI), or supported versions 22.12+ within Node 22 or Node 26+, and pnpm 11
- `uv` and Python 3.12 for running API tests or the API outside Docker
- AWS credentials and a **disposable Aurora DSQL test cluster** only for the explicitly gated cloud integration suite

## Run locally

From the repository root:

```sh
cp .env.example .env
docker compose up --build -d
uv run --directory services/api --locked alembic upgrade head
pnpm install --frozen-lockfile
pnpm dev:web
```

If your Docker installation exposes the standalone command, use `docker-compose up --build -d` instead. The standalone command was used to verify this scaffold on OrbStack on 2026-10-01.

Open <http://127.0.0.1:5173>. The page reports **API and database: ready** once the API can query PostgreSQL. Check the API directly with:

```sh
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/ready
```

`/health` checks the API process. `/health/ready` runs `SELECT 1` against the configured database backend and returns HTTP 503 if it cannot connect. Compose publishes PostgreSQL and the API only on `127.0.0.1`; the API binds inside its container so Compose can reach it. The sample credentials are for isolated local development only.

The first bootstrap downloads the locked Node/Python dependencies and PostgreSQL image. Once installed and the synthetic catalog is seeded, the app runtime makes no market-data, bank, model, or other provider calls and works offline. Ordinary startup and migrations create an empty catalog. Add securities and reviewed issuer links using the Local security and issuer catalog form, or explicitly seed the synthetic demo below.

Generate the exported FastAPI schema and TypeScript types after changing routes with `pnpm api:generate`. `pnpm check` regenerates both into a temporary directory and fails if either committed contract is stale.

### Synthetic offline demo

The demo is opt-in and never seeds automatically on API startup. For a local Compose database, copy `.env.example` to `.env`, set `DEMO_MODE=true`, start Compose, and apply migrations. Then seed explicitly from the host:

```sh
set -a
. ./.env
set +a
docker compose up --build -d
uv run --directory services/api --locked alembic upgrade head
uv run --directory services/api --locked python -m app.demo_seed
```

The seed contains only fictional synthetic accounts, two equities, two ETFs, USD cash, and dated synthetic prices. The web UI labels demo accounts. Repeating the seed adds no duplicates and does not overwrite existing rows. To destructively remove only the labelled demo fixture, run `DEMO_MODE=true uv run --directory services/api --locked python -m app.demo_seed --reset-demo`. Reset refuses when demo securities or accounts have been reused/edited by non-seed data. It does not remove unrelated accounts, securities, quotes, or snapshots. Expected owned totals are $660.00 taxable, $520.00 Roth IRA, and $1,180.00 combined; see [`fixtures/stage-0/expected-values.json`](fixtures/stage-0/expected-values.json). Those Stage 0 CSVs were originally illustrative; Stage 1 now supports reviewed position/fund imports. Use the Stage 1 templates for the delivered workflow.

The web page checks readiness immediately, then polls every 5 seconds. Each request has a 2-second timeout; failed checks show `unavailable`, and later successful checks restore `ready`. The current interval and timeout are defaults in `apps/web/src/readiness.ts`.

Copy `.env.example` to `.env` for local settings. The API defaults to `127.0.0.1` for host-based runs; Compose overrides the database host with its internal `db` service name. Leave `DATABASE_URL` blank to use the discrete database fields. A non-empty `DATABASE_URL` takes precedence over those fields. Vite reads `API_PORT` from the root `.env` for its `/api` proxy, with a shell `API_PORT` taking precedence; this value is used only by the Vite server.

Stop the containers with `docker compose down`. The named PostgreSQL volume is retained. The `.env` file and future `.private/` data are excluded from version control.

## Quality checks

```sh
pnpm install --frozen-lockfile
uv sync --directory services/api --locked
pnpm check
```

`pnpm check` first regenerates OpenAPI and TypeScript contracts into a temporary directory and fails if the committed generated files differ. It then runs ESLint and Ruff, Prettier and Ruff formatting checks, strict TypeScript and mypy checks, Vitest and pytest, then the production web build. Run `pnpm api:generate` to refresh contracts. The ordinary tests use synthetic data; PostgreSQL schema tests run when `TEST_DATABASE_URL` is set. GitHub Actions provides a disposable PostgreSQL 16 service for every quality run.

The API tests cover health/readiness, account and manual-position routes, stale two-client writes after refetch, immutable replacement history, arithmetic overflow/rounding/rollback, scoped identifier and alias identities, generated OpenAPI freshness, explicit backend and DSQL role validation, engine TLS/pool configuration, schema-drift rejection, migration-plan resumption, and capped OCC retry. Ordinary GitHub Actions CI provisions PostgreSQL 16 and runs fresh install plus populated `0002 → head` upgrade/manual replacement checks. A real DSQL suite remains gated on `RUN_DSQL_INTEGRATION=1` and `DSQL_TEST_CLUSTER=disposable`.

On 2026-10-02, the Stage 0 PostgreSQL 16 runtime suite passed locally against PostgreSQL 16.15: 50 passed and 3 DSQL tests skipped. It exercised a fresh install, a populated `0002 → head` upgrade, preserved snapshot history, subsequent replacement and rollback. Run that gate against a disposable PostgreSQL 16 database with `TEST_DATABASE_URL=postgresql+psycopg://... uv run --directory services/api --locked pytest -q`. The S0.6 SQLite-backed browser/API transcript is in [`docs/stage-0-demo-transcript.md`](docs/stage-0-demo-transcript.md); SQLite is not PostgreSQL or DSQL evidence. Live DSQL remains unverified.

## Database schema

The core schema is managed by Alembic. With Compose PostgreSQL running, apply the local migrations with:

```sh
uv run --directory services/api --locked alembic upgrade head
```

Export `DATABASE_URL` (using `postgresql+psycopg://`) or the `DATABASE_*` connection fields to choose local PostgreSQL. The opt-in PostgreSQL schema test uses `TEST_DATABASE_URL` and checks UUID, decimal, JSONB, provenance, uniqueness, and FK behavior.

Migrations `0001` and `0002` remain immutable. Migration `0003_immutable_position_revisions_and_identifiers` appends manual snapshot revisions, selects the current snapshot through an account pointer, reconciles existing counters, and adds issuer alias namespaces/review state plus scoped security identifiers. Prior revision payloads and lines stay unchanged; lifecycle status transitions from accepted to superseded as the pointer moves. DSQL applies each `ALTER TABLE`/table/index statement in its own DDL transaction and backfills existing revision state in bounded DML transactions.

Aurora DSQL uses the official `aurora-dsql-sqlalchemy` dialect and Python connector. Set `DATABASE_BACKEND=aurora_dsql`, `AWS_REGION`, `AURORA_DSQL_CLUSTER_ENDPOINT`, and `AURORA_DSQL_DB_USER`; obtain AWS credentials through the standard AWS credential chain or workload role. DSQL rejects `DATABASE_URL`. Schema migration also requires a separate `AURORA_DSQL_MIGRATION_DB_USER` role. Apply the versioned DSQL plan with:

```sh
uv run --directory services/api --locked python -m app.db.migrate_dsql
```

The runner uses one DDL statement per transaction, waits for asynchronous indexes, and records completed steps separately. When using `.env`, export its entries in the shell before running the command (`set -a; . ./.env; set +a`). Run `uv run --directory services/api --locked pytest -q tests/test_dsql_integration.py` only with `RUN_DSQL_INTEGRATION=1`, `DSQL_TEST_CLUSTER=disposable`, and a disposable cluster configured; the suite applies schema changes and writes/deletes synthetic rows. Local config, dialect compilation and mocked migration tests do not establish live DSQL compatibility. DSQL is **unverified**, so production promotion remains blocked.

The GitHub Actions workflow in `.github/workflows/quality.yml` installs locked dependencies and runs the same `pnpm check` on pushes and pull requests. It uses Node 24, Python 3.12, pnpm 11.19.0, and uv 0.11.13. The `main` branch publishes to the private GitHub repository [`jasonkli21/personal-finance-and-investments`](https://github.com/jasonkli21/personal-finance-and-investments); see its [Actions page](https://github.com/jasonkli21/personal-finance-and-investments/actions) for the current CI run status.

## Layout and next work

- `apps/web`: React, TypeScript, Vite, Tailwind, generated OpenAPI schema, and account/position workflow.
- `services/api`: FastAPI routes/domains, selected-backend readiness probe, and tests.
- `compose.yaml`: local PostgreSQL 16 and API containers.
- `docs/05-roadmap.md`: Stage 0–1 delivered; Stage 2–5 remain scoped future work.
- `services/api/app/integrations/personal_ai.py`: optional extraction protocol/candidate boundary, disabled runtime and synthetic fake.
- `fixtures/stage-0/`: synthetic positions/fund-holdings CSV examples and expected Decimal totals.

Aurora DSQL configuration keys in `.env.example` are placeholders and are not needed for local development. The current plan, verification status, checked package versions and AWS references are recorded in [`docs/07-aurora-dsql-compatibility.md`](docs/07-aurora-dsql-compatibility.md). Stage 1 local MVP is delivered; select a later-stage task only when requested. Its implementation plan and release evidence distinguish historical requirements from current behavior; the plan is in [`docs/stage-1-implementation-plan.md`](docs/stage-1-implementation-plan.md).
