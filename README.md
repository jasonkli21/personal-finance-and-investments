# Portfolio Intelligence

This repository contains the Stage 0 local foundation through S0.6: local tooling/schema, the Aurora DSQL boundary, account/manual-position workflow, and an explicit synthetic offline demo. Product requirements and later work packages are in [`docs/README.md`](docs/README.md). CSV imports and exposure calculations are not implemented yet.

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

Generate the exported FastAPI schema and TypeScript types after changing routes with `pnpm api:generate`.

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

The seed contains only fictional synthetic accounts, two equities, two ETFs, USD cash, and dated synthetic prices. The web UI labels demo accounts. Repeating the seed adds no duplicates and does not overwrite existing rows. To destructively remove only the labelled demo fixture, run `DEMO_MODE=true uv run --directory services/api --locked python -m app.demo_seed --reset-demo`. Reset refuses when demo securities or accounts have been reused/edited by non-seed data. It does not remove unrelated accounts, securities, quotes, or snapshots. Expected owned totals are $660.00 taxable, $520.00 Roth IRA, and $1,180.00 combined; see [`fixtures/stage-0/expected-values.json`](fixtures/stage-0/expected-values.json). CSVs are examples only; Stage 0 does not parse them.

The web page checks readiness immediately, then polls every 5 seconds. Each request has a 2-second timeout; failed checks show `unavailable`, and later successful checks restore `ready`. The current interval and timeout are defaults in `apps/web/src/readiness.ts`.

Copy `.env.example` to `.env` for local settings. The API defaults to `127.0.0.1` for host-based runs; Compose overrides the database host with its internal `db` service name. Leave `DATABASE_URL` blank to use the discrete database fields. A non-empty `DATABASE_URL` takes precedence over those fields. Vite reads `API_PORT` from the root `.env` for its `/api` proxy, with a shell `API_PORT` taking precedence; this value is used only by the Vite server.

Stop the containers with `docker compose down`. The named PostgreSQL volume is retained. The `.env` file and future `.private/` data are excluded from version control.

## Quality checks

```sh
pnpm install --frozen-lockfile
uv sync --directory services/api --locked
pnpm check
```

`pnpm check` runs ESLint and Ruff, Prettier and Ruff formatting checks, strict TypeScript and mypy checks, Vitest and pytest, then the production web build. It exits on the first failed check. Run `pnpm format` to apply formatting, or run `pnpm lint`, `pnpm format:check`, `pnpm typecheck`, `pnpm test`, and `pnpm build:web` separately. The ordinary tests use synthetic data and mocked database connections; these quality checks need no running containers or credentials. The opt-in schema integration test is skipped unless `TEST_DATABASE_URL` is set.

The API tests cover health/readiness, account and manual-position routes, revision conflicts, generated OpenAPI, explicit backend and DSQL role validation, engine TLS/pool configuration, dialect compilation, migration-plan resumption, and capped OCC retry. The web tests cover proxy port configuration and readiness timeouts, recovery, status changes, non-overlapping requests, and cleanup. The Compose services and Vite-to-API readiness proxy were smoke-tested with PostgreSQL 16 on 2026-10-01. A real DSQL suite is skipped unless `RUN_DSQL_INTEGRATION=1` and `DSQL_TEST_CLUSTER=disposable` are set.

The latest `pnpm check` passed on 2026-10-02: 7 Vitest tests, 37 pytest tests, and a successful web build. Three database integration tests were skipped (one requires PostgreSQL 16 and two require a disposable DSQL cluster). Alembic generated PostgreSQL upgrade SQL offline; the new migration has not yet run against a live PostgreSQL 16 test database. The S0.6 SQLite-backed browser/API transcript is in [`docs/stage-0-demo-transcript.md`](docs/stage-0-demo-transcript.md); SQLite is not PostgreSQL or DSQL evidence.

## Database schema

The core schema is managed by Alembic. With Compose PostgreSQL running, apply the local migrations with:

```sh
uv run --directory services/api --locked alembic upgrade head
```

Export `DATABASE_URL` (using `postgresql+psycopg://`) or the `DATABASE_*` connection fields to choose local PostgreSQL. The opt-in PostgreSQL schema test uses `TEST_DATABASE_URL` and checks UUID, decimal, JSONB, provenance, uniqueness, and FK behavior.

Migration `0002_position_snapshot_revision` adds a per-account compare-and-swap counter and a manual-snapshot revision. It is separate from the already-applied `0001` migration. DSQL applies each `ALTER TABLE` statement in its own DDL transaction.

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
- `docs/05-roadmap.md`: staged implementation plan.
- `fixtures/stage-0/`: synthetic positions/fund-holdings CSV examples and expected Decimal totals.

Aurora DSQL configuration keys in `.env.example` are placeholders and are not needed for local development. The current plan, verification status, checked package versions and AWS references are recorded in [`docs/07-aurora-dsql-compatibility.md`](docs/07-aurora-dsql-compatibility.md). Stage 1 CSV import and exposure work is next; its implementation plan is in [`docs/stage-1-implementation-plan.md`](docs/stage-1-implementation-plan.md).
