# Stage 0 implementation plan

**Status:** S0.1–S0.6 local foundation implemented; live DSQL remains unverified
**Updated:** 2026-10-02
**Roadmap coverage:** Work packages 0.1–0.6

This is the execution plan for the local foundation: a reproducible application with a persisted manual holding and an independently testable production database boundary. Read [the docs index](README.md), [product specification](01-product-spec.md), [architecture](02-architecture.md), and [DSQL contract](07-aurora-dsql-compatibility.md) first. Those requirements take precedence over proposed implementation names here.

The structure follows the phase plans in `personal-ai-system/docs`: scope, contracts, dependency ordering, independently demonstrable tasks, and a completion review. It adapts their delivery discipline to this application's SQL, financial arithmetic, and privacy requirements.

## Scope boundary

Stage 0 includes:

- React/TypeScript/Vite and FastAPI scaffolding, local PostgreSQL 16, lockfiles, and developer commands.
- Offline lint, formatting, type checking, tests, and non-deploying CI.
- Portable accounts, securities/issuers/identifiers, quotes, and position-snapshot persistence.
- A separate DSQL engine/migration/retry boundary and credentialed readiness spike.
- Account create/edit, local security lookup, manual holding entry, and retrieval after reload.
- An opt-in, synthetic, repeatable offline demo.

The smallest vertical slice is **create account → select seeded equity → enter quantity and dated manual price → reload persisted holding**. Affected modules are `accounts`, `securities`, `portfolio`, `prices`, database configuration, and the web API boundary.

CSV imports, ETF parsers/decomposition, PDF/OCR, AI, spending, tax lots, workers, authentication for remote hosting, and AWS application infrastructure are outside this stage. DSQL tests are a readiness exercise, not permission to launch production.

## Delivery conventions and cross-cutting requirements

- Review existing work before implementing a package. The docs index records 0.1 and 0.2; do not recreate tooling or treat uncommitted schema work as accepted delivery.
- Keep FastAPI handlers thin. Domain services receive repositories; only database modules know engine-specific SQL or authentication behavior.
- Generate UUIDs in application code. Persist authoritative financial values as `NUMERIC` and process them as `Decimal`; choose and document precision, scale, overflow, and rounding policy.
- Use UTC instants for recording/retrieval timestamps and explicit dates for statement-effective dates. Preserve currency and the meaning of each timestamp.
- Financial decimals cross the API as strings. The web may format them, but never calculates authoritative balances with JavaScript floating point.
- Never modify an applied migration. Version PostgreSQL and DSQL execution plans together, with separate DDL/DML transactions, one DSQL DDL statement per transaction, and explicit asynchronous-index readiness.
- Local settings bind published services to loopback. No credentials or private data belong in fixtures, logs, `.env.example`, or frontend bundles.
- No external API/model is required. A real DSQL result requires a real cluster; compilation, mocks, and PostgreSQL tests have distinct labels.

## Required verification matrix

| Surface | Required local evidence | DSQL evidence / gating |
| --- | --- | --- |
| Bootstrap | Locked install, Compose readiness, SPA/API proxy | Not required for scaffold |
| Quality gate | Lint, formatting, strict types, backend/web tests, build; intentional failure detection | No cloud dependency in routine CI |
| Core schema | Fresh install and upgrade on PostgreSQL 16; UUID/NUMERIC/JSONB/FK/uniqueness cases | Real create/upgrade and index-readiness test before production |
| Transactions | Rollback, safe batch bounds, injected retry/exhaustion | Real conflicting writes with bounded full-unit retry |
| Connection lifecycle | Invalid config and session cleanup | IAM login, TLS hostname verification, token renewal on new connection |
| Manual workflow | Route/domain tests and browser reload demo | Same repository behavior on real cluster before promotion |
| Demo | Repeat seed, isolated reset, no secrets/network | Never seed a production environment implicitly |

## Required implementation artifacts

Deliver settings validation, versioned schema migrations, repository/domain contracts, exported OpenAPI and generated TypeScript client, synthetic fixtures, and actual run/verification commands. Paths below describe intended artifacts, not claims they already exist.

**Required persisted records:**

| Record | Minimum fields and invariants |
| --- | --- |
| Account | UUID, name, account type, base currency, active/archive status, source type, timestamps |
| Issuer / alias | UUID, normalized name; alias value/namespace, source, review status; no ticker-only company merging |
| Security / identifier | UUID, type, display ticker/name, currency, nullable issuer; identifier namespace/exchange, validity interval, source and ambiguity handling |
| Position snapshot | UUID, account, effective date, provenance/source, acceptance timestamp, publication/revision state; one selected effective revision by documented policy |
| Position line | Snapshot, security or unresolved reference, decimal quantity, nullable reported/manual price and value, currency, raw/evidence reference, quality status |
| Quote | Security, decimal price, currency, as-of, provider/source, retrieved time, manual/observed status; retain conflicting observations |

Cash is represented explicitly as cash with a balance/currency, never inferred from a fabricated equity ticker. A cash security type is permitted by the logical schema, but company lookups and equity-price multiplication must not treat it as a stock.

**Stage 0 precision and rounding handoff:** Quantities use `NUMERIC(28,10)` (up to 18 integer digits and 10 fractional digits); quote/manual prices use `NUMERIC(24,10)` (up to 14 integer digits and 10 fractional digits); reported position values use `NUMERIC(28,10)`. API financial inputs and outputs are decimal strings and domain arithmetic uses Python `Decimal`. A non-cash reported value is quantity × dated reported price, rounded once to 10 fractional digits with `ROUND_HALF_UP`; explicit cash balance values use the balance directly. The manual API rejects absolute values at or above `10^18`, does not convert currencies, and leaves a missing price unavailable. The schema has no currency scale conversion or cents-only display rounding. PostgreSQL/DSQL persistence checks remain separately gated as recorded below.

**Required configuration and API contract:**

| Boundary | Required behavior |
| --- | --- |
| `DATABASE_BACKEND` | Explicit `postgres` or `aurora_dsql`; invalid backend fails startup |
| PostgreSQL configuration | Local database URL, bounded connection pool, no remote/public defaults |
| DSQL configuration | Region, cluster endpoint, non-admin role, IAM token on connect, verified TLS; migration identity separate |
| Feature/cost settings | Remote AI/account sync/paid fallback disabled; optional provider configuration must not break local boot |
| `GET /health` | Existing liveness contract; preserve existing readiness semantics separately |
| `/api/v1/accounts` | Create/list; `PATCH /{id}` edits or archives account metadata |
| `/api/v1/securities/resolve?q=` | Bounded local lookup; ambiguous/unknown result is explicit |
| `/api/v1/accounts/{id}/positions` | Get/replace manual snapshot with expected revision; no trade semantics |

Finalize exact schemas in OpenAPI before connecting UI. Include safe errors for malformed input, missing resources, stale revisions, and unavailable storage; never return ORM or driver exceptions.

## Dependency map

```text
S0.1 Scaffold ─> S0.2 Quality ─> S0.3 Core schema ─┬─> S0.4 DSQL spike
                                                └─> S0.5 Manual API/UI ─> S0.6 Demo
S0.4 local engine/retry contract ────────────────────> S0.5
S0.4 real-cluster evidence ──────────────────────────> production-readiness gate
S0.3 + S0.5 + S0.6 local evidence ───────────────────> Stage 1 local development
```

S0.4 has a local contract/tooling deliverable and a separate credentialed execution gate. Missing AWS access does not block the local MVP; it leaves DSQL unverified.

---

## Stage 0 — Local foundation

### S0.1 — Establish the runnable scaffold

**Dependencies:** none; inspect existing scaffold first.  
**Modules:** web shell, API entry point/settings, Compose.

**Goal:** run the app locally with no external-service account.

**Work:**

1. Establish `apps/web` and `services/api` with the prescribed stack, `pnpm`/`uv` lockfiles, and pinned PostgreSQL 16 image/version policy.
2. Provide health/readiness behavior, a Vite development API proxy, and a visible loading/ready/error state.
3. Add `.env.example`, ignored real environment files, private-data ignore rules, and local Compose startup ordering/readiness checks.
4. Document prerequisites, locked installation, development startup, stop, and persistent-volume behavior in the root README.

**Requirements:** bind host ports to `127.0.0.1`; preserve the database on ordinary stop; avoid provider calls in health checks; readiness failures must be actionable without exposing connection secrets.

**Acceptance criteria:**

- A clean checkout starts PostgreSQL and API with documented commands, then loads the SPA through Vite.
- API failure produces a recoverable browser state; API recovery needs no source edit.
- The lockfiles and environment example contain no secrets; local startup requires no AWS/model credentials.

**Out of scope:** finance schema, dashboards, cloud resources, and provider integration.

### S0.2 — Establish quality gates and CI

**Dependencies:** S0.1.  
**Modules:** backend/web test configuration, root scripts, GitHub Actions.

**Goal:** give later packages one trustworthy, offline verification entry point.

**Work:**

1. Configure Ruff formatting/lint, strict mypy, strict TypeScript, ESLint/Prettier, pytest, and Vitest for actual repository paths.
2. Keep `pnpm check` as the documented aggregate lint/format/type/test/web-build gate; expose component commands for debugging.
3. Run the same gate in GitHub Actions with locked installs and no deployment/cloud credentials.
4. Demonstrate intentional backend and frontend failures, restore the fixtures, and record local versus remote evidence separately.

**Requirements:** deterministic unit tests use injected clocks/fakes; routine CI must not fetch issuer data or start a model. Do not invent remote CI success from a configured workflow or local pass.

**Acceptance criteria:**

- The aggregate command exits unsuccessfully for a failing check and successfully after the failure is removed.
- A clean workflow uses the same scripts as local development.
- Documentation identifies observed results, command/date, and any remote run still unverified.

**Out of scope:** paid CI infrastructure, cloud deployment, and coverage targets unrelated to risk.

### S0.3 — Implement the portable core schema

**Dependencies:** S0.1, S0.2.  
**Modules:** `app/db`, accounts, securities, portfolio, prices; Alembic.

**Goal:** persist the manual portfolio without creating PostgreSQL-only assumptions.

**Work:**

1. Record decisions for money/quantity precision, currency handling, identifier namespaces, cash representation, snapshot replacement, and revision selection.
2. Implement ORM mappings and migration(s) for accounts, issuers/aliases, securities/identifiers, dated quote observations, position snapshots, and lines.
3. Add repository operations for lookup, account management, snapshot reads, and a bounded manual-snapshot write with an expected revision.
4. Separate publication metadata from staged lines so Stage 1 imports can expand the same semantics without exposing incomplete snapshots.
5. Produce the DSQL DDL execution plan, ledger/checkpoint behavior, and index dependencies even when the real execution gate remains pending.

**Requirements:** app UUIDs; documented `NUMERIC` precision; parameterized SQL; constrained relationships and scoped identifiers; bounded JSON metadata; no triggers, extension types, implicit generated IDs, or future spending/tax/research tables.

**Acceptance criteria:**

- Fresh and upgrade migrations succeed on actual PostgreSQL 16; constraints reject invalid references and duplicate scoped identities.
- Decimal quantities/prices round-trip without float conversion; zero quantities and unresolved identifiers are preserved.
- Two accounts holding the same security remain independent; failed replacement leaves the previous snapshot selected.
- DSQL plan proves DDL/DML separation and index waiting structurally; real execution is explicitly unverified unless performed.

**Out of scope:** assuming ORM DDL compilation proves DSQL compatibility; full ETF/import schemas; migration of real user data.

### S0.4 — Implement and exercise the DSQL readiness boundary

**Dependencies:** S0.2, S0.3.  
**Modules:** engine factory, migration runner, transaction helper, gated integration tests.  
**Decision required:** AWS account/region/test access and bounded spend before real cluster execution.

**Goal:** verify that the chosen persistence approach works on the required production database.

**Work:**

1. Reverify official dialect/connector versions, supported SQL/types, IAM/TLS guidance, and limits referenced by the DSQL contract; record check dates when implementing.
2. Add a separate DSQL engine using the official dialect/connector. Obtain tokens for each new connection; test pool reconnect and session cleanup.
3. Execute versioned migrations with one DDL per transaction; wait for asynchronous indexes before marking dependent steps complete; support safe resumption after a failed step.
4. Implement bounded database-only OCC retry with a new session per attempt, capped exponential backoff/jitter, and explicit retryable error classification.
5. Run minimal real-cluster migration, CRUD, numeric/UUID/JSONB, FK, reconnect, and concurrent-conflict tests using synthetic data and a documented cleanup procedure.

**Requirements:** never retain static IAM passwords in URLs/logs; use verified TLS and scoped application/migration identities; no network/model work inside retried transactions. Dry-run/mocked migration tests and live results must be reported separately.

**Acceptance criteria:**

- Local tests reject invalid backend/configuration and prove retry cap/exhaustion and non-retryable errors.
- Real DSQL evidence identifies schema version, dialect version, cluster environment class, test commands/results, and resource cleanup without credentials.
- A conflict repeats only the DB unit; an external-call counter remains unchanged.
- If AWS access is unavailable, deliver the runner/config/test contract and mark the real-cluster gate **unverified**; production remains blocked.

**Out of scope:** application deployment, production financial data, multi-region clusters, and treating a local PostgreSQL pass as cloud evidence.

**S0.4 delivery evidence (2026-10-01):** `DatabaseEngineFactory` uses the official `aurora-dsql-sqlalchemy` 1.3.0 dialect/connector with token-on-connect, `verify-full` TLS, separate app and migration roles, bounded pooling, and a 3,000-second recycle. The versioned DSQL core plan uses seven single-statement table DDL transactions, four asynchronous index DDL transactions with `sys.wait_for_job`, and standalone ledger DML. Local tests check configuration, official dialect compilation, migration step boundaries/resumption, and capped retry. The real DSQL integration suite is explicitly opt-in for a disposable cluster and was not run; production remains blocked pending that evidence.

**S0.5 delivery evidence (2026-10-02):** Added Alembic revision `0002_position_snapshot_revision` and its two single-statement DSQL `ALTER TABLE` steps. Accounts keep a compare-and-swap revision counter; dated manual snapshots have a revision, and replacing a snapshot either updates that effective date or marks the prior accepted date superseded. Account create/list/edit/archive, bounded local security lookup, snapshot retrieval/replacement and safe conflict/validation errors are exposed under `/v1`. `pnpm api:generate` exports FastAPI OpenAPI and regenerates the web TypeScript schema. The UI uses TanStack Query, string financial inputs, account-scoped editing, source/date/quality labels, missing-price state and stale-revision reload behavior. Synthetic API tests exercise independent accounts, same-security holdings, cash balances, decimals, invalid/unknown securities, archived accounts, missing prices, dated revisions and stale writes. `pnpm check` passed on 2026-10-02 (7 Vitest tests, 30 pytest tests, web build); three opt-in database tests were skipped (one PostgreSQL and two DSQL). Alembic generated the PostgreSQL upgrade SQL offline, but no Docker client or `TEST_DATABASE_URL` was available to execute the fresh PostgreSQL 16 migration. Live DSQL remains unverified.

**S0.6 delivery evidence (2026-10-02):** Demo records are created only by running `python -m app.demo_seed` while `DEMO_MODE=true`; configuration rejects DSQL, arbitrary hosts, and a database URL in demo mode. Stable UUIDv5 identities, dated synthetic quotes/snapshots, and synthetic source/quality labels make a second seed a no-op; it does not update any existing fixture row. `--reset-demo` is destructive only to the fixed demo IDs and refuses if demo account snapshots include non-seed line sources or the synthetic securities are referenced by non-demo accounts, quotes, or securities. It deletes only demo fixture data. The UI labels demo accounts. Synthetic position and illustrative fund-holdings CSVs, expected Decimal totals, and a future document-fixture specification live in `fixtures/stage-0/`; no CSV/PDF parser was added. The startup, migration, seed, check and reset commands are in the root README. The browser transcript and local quality results are in [`stage-0-demo-transcript.md`](stage-0-demo-transcript.md). No schema migration or provider integration was required. PostgreSQL runtime and live DSQL evidence remain distinct and are not inferred from SQLite/unit/UI smoke checks.

### S0.5 — Deliver account and manual-position API/UI

**Dependencies:** S0.3; S0.4's local engine/transaction contract.  
**Modules:** accounts, securities, portfolio, prices; web account/position features.

**Goal:** complete the first persisted financial interaction.

**Work:**

1. Define typed account, security lookup, manual snapshot, and response/error contracts; export OpenAPI and generate the TypeScript client.
2. Implement domain services and routes for account create/edit/archive, local fixture lookup, and manual snapshot replacement.
3. Require explicit account, security, currency, quantity, effective date, and dated manual price when valuation is requested; preserve missing prices as unavailable.
4. Build labelled keyboard-accessible forms, pending/error/conflict states, account selection, and persisted holding display through TanStack Query.
5. Invalidate affected queries after a confirmed write; handle stale revisions by reloading and asking for a deliberate resubmission rather than overwriting invisibly.

**Requirements:** metadata edits do not alter other accounts; deleting a line creates a replacement revision rather than a fictitious sale; cash has explicit currency/balance; manual snapshots do not establish basis/history. Display source/date beside values.

**Acceptance criteria:**

- A user creates two accounts, adds the same equity separately, edits one holding, and retrieves both correctly after restart/reload.
- Missing price, invalid decimal/date/currency, unknown security, archived account, and stale revision produce safe UI/API outcomes.
- API tests prove failed writes do not partially change a snapshot; generated types match exported OpenAPI.
- The manual-stock path works with network access to providers disabled.

**Out of scope:** CSV review, quoted-market integrations, exposure calculations, and tax-lot claims.

### S0.6 — Package the synthetic offline demo and handoff

**Dependencies:** S0.5.  
**Modules:** fixture loading, docs, browser smoke procedure.

**Goal:** make the delivered slice reproducible and safe to inspect.

**Work:**

1. Add synthetic accounts, equities, ETFs, cash, dated manual prices, and expected owned values; seed only in explicit local/demo mode.
2. Make repeated seed runs idempotent through stable fixture identities; isolate reset to labelled demo data and document any destructive command explicitly.
3. Include synthetic position/fund CSV and later-document fixture specifications without implementing future parsers.
4. Record a manual browser transcript for create → enter → reload; document actual migration, seed, test, and startup commands.
5. Hand off schema versions, precision/rounding choices, API/client generation, known gaps, and separate PostgreSQL/DSQL test status to Stage 1.

**Requirements:** no institution/account information copied from real statements; seeding performs no downloads or model calls; source dates and synthetic labels are visible. Do not enable demo/reset commands implicitly in production.

**Acceptance criteria:**

- A fresh local environment demonstrates the slice with no secrets/provider signup.
- Re-running the seed does not duplicate accounts, securities, quotes, or holdings.
- Documented expected totals match the persisted fixture, including cash counted once.
- Completion evidence distinguishes historical recorded checks from checks actually rerun for this delivery.

**Out of scope:** pretending synthetic ETFs have verified issuer holdings, OCR benchmarking, or AWS provisioning.

## Stage 0 completion review

Before declaring the **local** foundation complete, verify all local acceptance criteria and answer:

1. Can a clean checkout start, migrate, test, and demonstrate a persisted manual holding offline?
2. Are financial values decimal, dated, currency-labelled, and attributable?
3. Are snapshots distinct from trades and accounts isolated from one another?
4. Does the API generate the web contract, with safe validation/conflict errors?
5. Are migrations immutable/versioned and DSQL-specific execution/retry boundaries explicit?
6. Is live DSQL evidence either recorded accurately or clearly marked unverified?

Stage 1 local work can proceed once the local answers are yes and the DSQL path is implemented as a separately gated package. **Production readiness additionally requires the real S0.4 checks and the later feature-specific DSQL suite.**

**Implementation handoff:** link the actual commands, migration ledger, accepted decisions, fixture expectations, generated client procedure, and local/cloud evidence in the docs index. This plan authorizes planning only; it does not record future tasks as completed.
