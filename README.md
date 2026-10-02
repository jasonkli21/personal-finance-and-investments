# Portfolio Intelligence

This repository contains the Stage 0.1 local scaffold, Stage 0.2 development quality tooling, and Stage 0.3 core PostgreSQL schema for the planned portfolio application. Product requirements and later work packages are in [`docs/README.md`](docs/README.md). Account and position APIs, imports, and exposure calculations are not implemented yet.

## Requirements

- Docker with Compose for PostgreSQL 16 and the API
- Node.js 24 (used in CI), or supported versions 22.12+ within Node 22 or Node 26+, and pnpm 11
- `uv` and Python 3.12 for running API tests or the API outside Docker

## Run locally

From the repository root:

```sh
cp .env.example .env
docker compose up --build -d
pnpm install --frozen-lockfile
pnpm dev:web
```

If your Docker installation exposes the standalone command, use `docker-compose up --build -d` instead. The standalone command was used to verify this scaffold on OrbStack on 2026-10-01.

Open <http://127.0.0.1:5173>. The page reports **API and database: ready** once the API can query PostgreSQL. Check the API directly with:

```sh
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/ready
```

`/health` checks the API process. `/health/ready` runs `SELECT 1` against PostgreSQL and returns HTTP 503 if it cannot connect. Compose publishes PostgreSQL and the API only on `127.0.0.1`; the API binds inside its container so Compose can reach it. The sample credentials are for isolated local development only.

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

The API tests cover `/health`, OpenAPI generation, database failure reporting, discrete connection fields, explicit URL overrides, invalid ports, and rejection of the unimplemented Aurora DSQL backend. The web tests cover proxy port configuration and readiness timeouts, recovery, status changes, non-overlapping requests, and cleanup. The Compose services and Vite-to-API readiness proxy were smoke-tested with PostgreSQL 16 on 2026-10-01, including a custom API port and a synthetic password containing URL-reserved characters.

## Database schema

The core schema is managed by Alembic. With Compose PostgreSQL running, apply the local migration with:

```sh
uv run --directory services/api --locked alembic upgrade head
```

Export `DATABASE_URL` (using `postgresql+psycopg://`) or the `DATABASE_*` connection fields to choose a local PostgreSQL database. The migration runner explicitly rejects `DATABASE_BACKEND=aurora_dsql`; the separate DSQL runner is Stage 0.4 work. For a disposable PostgreSQL 16 database, set `TEST_DATABASE_URL` and run `uv run --directory services/api --locked pytest -q tests/test_core_schema.py` to apply the migration and check UUID, decimal, JSONB, provenance, uniqueness, and foreign-key behavior. The fresh migration and integration test passed on a disposable PostgreSQL 16 container on 2026-10-01, and `pnpm check` passed. DSQL migration and integration status is **unverified**.

The GitHub Actions workflow in `.github/workflows/quality.yml` installs locked dependencies and runs the same `pnpm check` on pushes and pull requests. It uses Node 24, Python 3.12, pnpm 11.19.0, and uv 0.11.13. The `main` branch publishes to the private GitHub repository [`jasonkli21/personal-finance-and-investments`](https://github.com/jasonkli21/personal-finance-and-investments); see its [Actions page](https://github.com/jasonkli21/personal-finance-and-investments/actions) for the current CI run status.

## Layout and next work

- `apps/web`: React, TypeScript, Vite, and Tailwind scaffold.
- `services/api`: FastAPI process, PostgreSQL readiness probe, and smoke tests.
- `compose.yaml`: local PostgreSQL 16 and API containers.
- `docs/05-roadmap.md`: staged implementation plan.

Aurora DSQL configuration keys in `.env.example` are placeholders for Stage 0.4. No DSQL connection or integration test has been implemented or run. The DSQL DDL plan and current schema caveats are recorded in [`docs/07-aurora-dsql-compatibility.md`](docs/07-aurora-dsql-compatibility.md). The next planned package is Stage 0.4 DSQL readiness.
