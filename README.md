# Portfolio Intelligence

The local app includes reviewed position/fund imports, dated owned valuation, reconciled ETF exposure, frozen reports/export, text-layer brokerage PDF jobs, reviewed bank/card CSV transactions, finance summaries, historical performance, supplied tax lots, hypothetical sale/allocation/liquidity planning, and manual source-linked research. Stage 2 remains partial; Stage 3 is locally delivered; Stage 4 deployment tooling is prepared; Stage 5 provides an offline baseline. Scanned documents, live AI/retrieval, account sync and research monitoring remain gated. The app works with PostgreSQL 16 and no provider keys. Production targets GCP/Neon; hosted checks remain pending. See the [documentation index](docs/README.md) and [maintainability review](docs/maintainability-review.md) for current scope and evidence.

Reusable AI capabilities will integrate through `personal-ai-system`; finance retains authoritative data, deterministic validation/calculations, workflows and UI. The current `PersonalAIClient` is a disabled extraction boundary with a synthetic fake, not a live integration. Leave `PERSONAL_AI_ENABLED=false`; true fails startup until an upstream contract and security/data-handling gates are implemented. See [ADR 0001](docs/adr/0001-shared-personal-ai.md). No AI service or model credentials are needed for local imports.

## Requirements

- Docker with Compose for PostgreSQL 16 and the API
- Node.js 24 (used in CI), or supported versions 22.12+ within Node 22 or Node 26+, and pnpm 11
- `uv` and Python 3.12 for running API tests or the API outside Docker
- Cloud credentials only for explicitly opted-in disposable Neon/GCP checks; none required locally

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

The API image prepares `/app/.private` as UID/GID 10001 with mode 0700, which
new `private_files` volumes inherit. If an older local volume was created with
root-owned files, repair only that named private-file volume before starting
the API:

```sh
docker compose run --rm --user 0:0 --entrypoint chown api -R 10001:10001 /app/.private
```

This targets only `/app/.private`; do not apply recursive ownership changes to
the repository, PostgreSQL volume, or other host paths.

## Quality checks

```sh
pnpm install --frozen-lockfile
uv sync --directory services/api --locked
pnpm check
```

`pnpm check` first regenerates OpenAPI and TypeScript contracts into a temporary directory and fails if the committed generated files differ. It then runs ESLint and Ruff, Prettier and Ruff formatting checks, strict TypeScript and mypy checks, Vitest, infrastructure guardrails and pytest, then the production web build. Two historical applied migrations (`0007` and `0015`) are excluded only from formatting; lint and migration checks still cover them. Run `pnpm api:generate` to refresh contracts. The ordinary tests use synthetic data; PostgreSQL schema tests run when `TEST_DATABASE_URL` is set, and isolated encrypted recovery drills additionally require a loopback `STAGE4_RECOVERY_TEST_ADMIN_URL` ending in `/postgres`. GitHub Actions provides a disposable PostgreSQL 16 service for every quality run. Browser journeys run separately with `pnpm test:e2e` and require the disposable E2E database opt-in.

The API suite covers synthetic finance workflows, auth, storage, job fencing/cancellation, DB-only retry, fresh/populated PostgreSQL migrations and encrypted recovery. Browser journeys require E2E_DISPOSABLE_DATABASE=1 and a loopback E2E_DATABASE_URL ending _test. Real hosted evidence remains pending; see [the migration record](docs/gcp-neon-migration.md).

## Database schema

The core schema is managed by Alembic. With Compose PostgreSQL running, apply the local migrations with:

```sh
uv run --directory services/api --locked alembic upgrade head
```

Export `DATABASE_URL` (using `postgresql+psycopg://`) or the `DATABASE_*` connection fields to choose local PostgreSQL. The opt-in PostgreSQL schema test uses `TEST_DATABASE_URL` and checks UUID, decimal, JSONB, provenance, uniqueness, and FK behavior.

Migrations `0001` and `0002` remain immutable. Migration `0003_immutable_position_revisions_and_identifiers` appends manual snapshot revisions, selects the current snapshot through an account pointer, reconciles existing counters, and adds issuer alias namespaces/review state plus scoped security identifiers. Prior revision payloads and lines stay unchanged; lifecycle status transitions from accepted to superseded as the pointer moves. The same Alembic history is canonical for Neon. Set DATABASE_URL for runtime and optional MIGRATION_DATABASE_URL for a direct schema migration connection. In production both use verified TLS with a Neon host, sslmode=verify-full and sslrootcert=system. Cloud Run injects the runtime URL from a pinned Secret Manager version; migration credentials stay operator-only. See [the database contract](docs/07-postgres-neon.md).

GCP infrastructure is prepared in [infra/terraform](infra/terraform/README.md): Cloud Run API and bounded worker Job, private GCS, Firebase Hosting same-origin /api, Artifact Registry, Secret Manager and scoped service identities. Auth remains OIDC/PKCE with revocable DB sessions. Firebase cookie/path transport is handled explicitly by the backend. No resources were deployed during migration. Run the real disposable Neon suite only with RUN_NEON_INTEGRATION=1, NEON_TEST_DATABASE=disposable and dedicated runtime/direct test URLs. Personal-data promotion also requires GCP auth/private-object/recovery evidence.

The GitHub Actions workflow in `.github/workflows/quality.yml` installs locked dependencies and runs the same `pnpm check` on pushes and pull requests. It uses Node 24, Python 3.12, pnpm 11.19.0, and uv 0.11.13. The `main` branch publishes to the private GitHub repository [`jasonkli21/personal-finance-and-investments`](https://github.com/jasonkli21/personal-finance-and-investments); see its [Actions page](https://github.com/jasonkli21/personal-finance-and-investments/actions) for the current CI run status.

## Layout and next work

- `apps/web/src`: React workspaces, shared form/response helpers and generated OpenAPI schema; unit tests in `apps/web/test`, browser journeys in `apps/web/e2e`.
- `services/api/app`: FastAPI routes, finance domains, adapters, auth, workers and operator recovery/release tooling; backend tests in `services/api/tests`.
- `tests/infra`: offline Terraform policy/configuration guardrails, included in `pnpm check`.
- `compose.yaml`: local PostgreSQL 16 and API containers.
- `docs/05-roadmap.md`: milestone requirements; stage release records distinguish delivered code from remaining integration and launch gates.
- `services/api/app/integrations/personal_ai.py`: optional extraction protocol/candidate boundary, disabled runtime and synthetic fake.
- `fixtures/stage-0/`: synthetic positions/fund-holdings CSV examples and expected Decimal totals.

Cloud settings in .env.example are blank placeholders; do not commit actual secrets. [ADR 0002](docs/adr/0002-gcp-neon.md) and [Stage 4 operations](docs/stage-4-operations-runbook.md) define the current target. Exact dated predecessor release facts are preserved under docs/history/pre-gcp-neon. Follow code and release evidence; plans alone do not prove completion. The API image disables Uvicorn's query-bearing access log and emits redacted request records with route templates, status, duration and request ID through the server logger.
