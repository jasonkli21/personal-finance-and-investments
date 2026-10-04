> Historical snapshot at `4e5f3e3`, preserved 2026-10-03. Deployment guidance is superseded by [ADR 0002](../../adr/0002-gcp-neon.md). Do not use this snapshot as current instructions.

# Stage 0 implementation plan

**Status:** S0.1–S0.6 delivered; Stage 0 local exit gate passed on PostgreSQL 16.15; live DSQL remains unverified
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

Historical delivery notes below reflect the environment at each recorded run; the later Stage 0 PostgreSQL exit evidence and Stage 1 release supersede earlier “unverified locally” statements. The [shared-AI ADR](adr/0001-shared-personal-ai.md) reconciles future integration direction without changing this delivered foundation.

## Delivery conventions and cross-cutting requirements

- Review existing work before implementing a package. The docs index records 0.1 and 0.2; do not recreate tooling or treat uncommitted schema work as accepted delivery.
- Keep FastAPI handlers thin and domain logic outside routes. Current S0.5 domain functions receive a SQLAlchemy `Session` directly; a separate repository-object layer is not implemented. Treat this as the documented Stage 0 persistence convention until Stage 1 demonstrates a need for repositories. Only database modules know engine-specific SQL or authentication behavior.
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
| Quality gate | Lint, formatting, strict types, backend/web tests, build; intentional failure detection; OpenAPI and generated TypeScript must match committed outputs | No cloud dependency in routine CI |
| Core schema | PostgreSQL 16 fresh install and populated 0001 → head upgrade; fixture contains at least two accounts, multiple dates, accepted/superseded snapshots and lines; UUID/NUMERIC/JSONB/FK/uniqueness cases | Real create/upgrade and index-readiness test before production |
| Transactions | Rollback, safe batch bounds, injected retry/exhaustion | Real conflicting writes with bounded full-unit retry |
| Connection lifecycle | Invalid config and session cleanup | IAM login, TLS hostname verification, token renewal on new connection |
| Manual workflow | PostgreSQL-backed replacement, immutable prior contents, conflict, rollback and reload tests; browser reload demo | Same persistence behavior, replacement and retry tests on real cluster before promotion |
| Demo | Repeat seed, isolated reset, no secrets/network | Never seed a production environment implicitly |

PostgreSQL integration runs in ordinary CI against a disposable PostgreSQL 16 service. A skipped database test or offline Alembic SQL generation does not satisfy this matrix.

## Required implementation artifacts

Deliver settings validation, versioned schema migrations, data-access/domain contracts, exported OpenAPI and generated TypeScript client, synthetic fixtures, and actual run/verification commands. Paths below describe intended artifacts, not claims they already exist.

**Required persisted records:**

| Record | Minimum fields and invariants |
| --- | --- |
| Account | UUID, name, account type, base currency, active/archive status, source type, timestamps |
| Issuer / alias | UUID, normalized name; alias value/namespace, source, review status; aliases shared across issuers remain ambiguous until reviewed; no ticker-only company merging |
| Security / identifier | UUID, type, display ticker/name, currency, nullable issuer; separate identifier UUID, security, namespace/exchange-scoped value, validity interval, source and review status; identity collisions are surfaced, not silently merged |
| Position snapshot | UUID, account, effective date, provenance/source, acceptance timestamp and immutable published revision; one `current_position_snapshot_id` pointer per account selects the accepted revision |
| Position line | Snapshot, security or unresolved reference, decimal quantity, nullable reported/manual price and value, currency, raw/evidence reference, quality status |
| Quote | Security, decimal price, currency, as-of, provider/source, retrieved time, manual/observed status; retain conflicting observations |

Cash is represented explicitly as cash with a balance/currency, never inferred from a fabricated equity ticker. A cash security type is permitted by the logical schema, but company lookups and equity-price multiplication must not treat it as a stock. Replacing a published snapshot appends a new snapshot and lines; prior revision payloads and lines remain available and immutable. The prior snapshot's lifecycle status may change from `accepted` to `superseded`; the account pointer and compare-and-swap revision counter advance together in the same bounded database transaction.

**Stage 0 precision and rounding handoff:** Quantities use `NUMERIC(28,10)` (up to 18 integer digits and 10 fractional digits); quote/manual prices use `NUMERIC(24,10)` (up to 14 integer digits and 10 fractional digits); reported position values use `NUMERIC(28,10)`. API financial inputs and outputs are decimal strings and domain arithmetic uses Python `Decimal` with an explicit local context. Check product bounds before quantization and convert decimal arithmetic failures to safe validation errors. A non-cash reported value is quantity × dated reported price, rounded once to 10 fractional digits with `ROUND_HALF_UP`; explicit cash balance values use the balance directly. The manual API rejects absolute values at or above `10^18`, does not convert currencies, and leaves a missing price unavailable. The schema has no currency scale conversion or cents-only display rounding. PostgreSQL/DSQL persistence checks remain separately gated as recorded below.

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
5. Run ordinary CI with a disposable PostgreSQL 16 service and check that regenerating both OpenAPI JSON and TypeScript declarations produces no diff.

**Requirements:** deterministic unit tests use injected clocks/fakes; routine CI must not fetch issuer data or start a model. Do not invent remote CI success from a configured workflow or local pass.

**Acceptance criteria:**

- The aggregate command exits unsuccessfully for a failing check and successfully after the failure is removed.
- A clean workflow uses the same scripts as local development.
- `pnpm check` fails if either committed generated contract is stale; the workflow executes database integration against its PostgreSQL 16 service.
- Documentation identifies observed results, command/date, and any remote run still unverified.

**Out of scope:** paid CI infrastructure, cloud deployment, and coverage targets unrelated to risk.

### S0.3 — Implement the portable core schema

**Dependencies:** S0.1, S0.2.  
**Modules:** `app/db`, accounts, securities, portfolio, prices; Alembic.

**Goal:** persist the manual portfolio without creating PostgreSQL-only assumptions.

**Work:**

1. Record decisions for money/quantity precision, currency handling, identifier namespaces, cash representation, snapshot replacement, and revision selection.
2. Implement ORM mappings and migration(s) for accounts, issuers/aliases, securities/identifiers, dated quote observations, position snapshots, and lines.
3. Add data-access operations for lookup, account management, snapshot reads, and a bounded manual-snapshot write with an expected revision. Stage 0's domain functions receive SQLAlchemy `Session` directly; separate repository objects are not part of this slice.
4. Separate publication metadata from staged lines so Stage 1 imports can expand the same semantics without exposing incomplete snapshots.
5. Produce the DSQL DDL execution plan, ledger/checkpoint behavior, and index dependencies even when the real execution gate remains pending.

**Requirements:** app UUIDs; documented `NUMERIC` precision; parameterized SQL; constrained relationships and scoped identifiers; bounded JSON metadata; no triggers, extension types, implicit generated IDs, or future spending/tax/research tables.

**Acceptance criteria:**

- Fresh migrations and a populated 0001 → head upgrade succeed on actual PostgreSQL 16. The populated fixture has multiple accounts, several effective dates, accepted and superseded snapshots, lines, identifiers and aliases; after upgrade, verify all prior content, revision selection, counters, uniqueness and a successful subsequent replacement.
- Constraints reject invalid references and duplicate scoped identities. Identifier identity is scoped by namespace/exchange/value; issuer aliases retain namespace and review status, and cross-issuer collisions remain detectable as ambiguity.
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
3. Execute versioned migrations with one DDL per transaction; wait for asynchronous indexes before marking dependent steps complete; support safe resumption after a failed step and validate complete expected object definitions before adopting pre-existing tables, columns, constraints or indexes.
4. Implement bounded database-only OCC retry with a new session per attempt, capped exponential backoff/jitter, and explicit retryable error classification.
5. Keep a gated real-cluster suite for fresh and populated upgrades, CRUD, manual same-date replacement/history retention, numeric/UUID/JSONB, FK/uniqueness, index readiness, schema-drift rejection, IAM token renewal after expiry, reconnect and concurrent-conflict tests using synthetic data and documented cleanup.

**Requirements:** never retain static IAM passwords in URLs/logs; use verified TLS and scoped application/migration identities; no network/model work inside retried transactions. Dry-run/mocked migration tests and live results must be reported separately.

**Acceptance criteria:**

- Local tests reject invalid backend/configuration and prove retry cap/exhaustion and non-retryable errors.
- Real DSQL evidence identifies schema version, dialect version, cluster environment class, test commands/results, and resource cleanup without credentials.
- A conflict repeats only the DB unit; an external-call counter remains unchanged.
- If AWS access is unavailable, deliver the runner/config/test contract and mark the real-cluster gate **unverified**; production remains blocked.

**Out of scope:** application deployment, production financial data, multi-region clusters, and treating a local PostgreSQL pass as cloud evidence.

**S0.4 delivery evidence (2026-10-02):** `DatabaseEngineFactory` uses the official `aurora-dsql-sqlalchemy` 1.3.0 dialect/connector with token-on-connect, `verify-full` TLS, separate app and migration roles, bounded pooling, and a 3,000-second recycle. The versioned DSQL plan has 27 steps across the original seven tables/four indexes and the new identifier table, scoped indexes, schema alterations, constraints, and bounded revision backfill. Local tests check configuration, official dialect compilation, migration step boundaries/resumption, schema drift rejection and capped retry. The real DSQL integration suite is explicitly opt-in for a disposable cluster and was not run; populated-upgrade preservation and token-expiry reconnection also remain pending live evidence. Production remains blocked.

The DSQL completion contract also includes checks not covered by the original two live tests: populated-upgrade preservation, replacement with immutable earlier contents, scoped identifier/alias uniqueness and ambiguity, incompatible pre-existing-schema rejection, and a new IAM-authenticated connection after token expiry. These remain **pending live evidence** even after migration and CRUD smoke tests pass.

**S0.5 delivery evidence (2026-10-02):** Alembic revision `0003_immutable_position_revisions_and_identifiers` adds append-only account-selected position revisions, reconciles accepted legacy manual snapshots, and adds scoped security identifiers and issuer alias review metadata. API writes use account-level compare-and-swap; the UI captures the base revision with the draft, and refetch does not advance it. Decimal valuation uses an explicit context and checks range before quantization. Tests cover two-client stale-draft conflicts after refetch, max-input and rounding behavior, rollback/history, scoped identity collisions, and a PG16 populated-upgrade CI fixture. OpenAPI/TypeScript freshness is part of `pnpm check`. PostgreSQL runtime tests remain unverified locally because no server/URL is available; DSQL remains unverified pending a live cluster.

**S0.6 delivery evidence (2026-10-02):** Demo records are created only by running `python -m app.demo_seed` while `DEMO_MODE=true`; configuration rejects DSQL, arbitrary hosts, and a database URL in demo mode. Stable UUIDv5 identities, dated synthetic quotes/snapshots, and synthetic source/quality labels make a second seed a no-op; it does not update any existing fixture row. `--reset-demo` is destructive only to the fixed demo IDs and refuses if demo account snapshots include non-seed line sources or the synthetic securities are referenced by non-demo accounts, quotes, or securities. It deletes only demo fixture data. The UI labels demo accounts. Synthetic position and illustrative fund-holdings CSVs, expected Decimal totals, and a future document-fixture specification live in `fixtures/stage-0/`; no CSV/PDF parser was added. The startup, migration, seed, check and reset commands are in the root README. The browser transcript and local quality results are in [`stage-0-demo-transcript.md`](stage-0-demo-transcript.md). No schema migration or provider integration was required. PostgreSQL runtime and live DSQL evidence remain distinct and are not inferred from SQLite/unit/UI smoke checks.

**Stage 0 PostgreSQL exit evidence (2026-10-02):** Installed PostgreSQL 16.15 as an isolated local test runtime and ran `TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55432/portfolio_stage0_gate uv run --directory services/api --locked pytest -q`: **50 passed, 3 skipped**. The two opt-in schema tests ran against the disposable PG16 database. Fresh migration and populated `0002 → head` upgrade both passed, including snapshot preservation, a subsequent replacement and rollback. The first run exposed that Alembic's default `VARCHAR(32)` version ledger could not store revision `0003_immutable_position_revisions_and_identifiers`; `alembic/env.py` now creates or widens this PostgreSQL bookkeeping column to 128 characters before applying migrations. The subsequent aggregate `pnpm check` passed (8 Vitest, 48 pytest, 5 PostgreSQL/DSQL tests skipped, generated API freshness, lint, formatting, type checks and web build). This local exit gate does not imply a successful remote CI run or a live DSQL result.

### S0.5 — Deliver account and manual-position API/UI

**Dependencies:** S0.3; S0.4's local engine/transaction contract.  
**Modules:** accounts, securities, portfolio, prices; web account/position features.

**Goal:** complete the first persisted financial interaction.

**Work:**

1. Define typed account, security lookup, manual snapshot, and response/error contracts; export OpenAPI and generate the TypeScript client.
2. Implement domain services and routes for account create/edit/archive, local fixture lookup, and manual snapshot replacement.
3. Require explicit account, security, currency, quantity, effective date, and dated manual price when valuation is requested; preserve missing prices as unavailable.
4. Build labelled keyboard-accessible forms, pending/error/conflict states, account selection, and persisted holding display through TanStack Query.
5. Capture the base account revision with the editable draft, including revision `0` for an account with no published snapshot. Background refetches update server state only; they never update that draft's base revision. Invalidate affected queries after a confirmed write; stale revisions show a conflict and require a deliberate reload before resubmission.
6. Publish replacements append-only. Never change or delete a prior revision's effective date, source, revision number, accepted timestamp, or lines. Its lifecycle status may transition from `accepted` to `superseded`; atomically move the account's current-snapshot pointer and advance its current revision. The selected pointer, rather than query freshness or maximum effective date, defines the currently selected manual snapshot.

**Requirements:** metadata edits do not alter other accounts; deleting a line creates a replacement revision rather than a fictitious sale; cash has explicit currency/balance; manual snapshots do not establish basis/history. Display source/date beside values.

**Acceptance criteria:**

- A user creates two accounts, adds the same equity separately, edits one holding, and retrieves both correctly after restart/reload.
- Missing price, invalid decimal/date/currency, unknown security, archived account, and stale revision produce safe UI/API outcomes.
- A two-client/refetch test holds a revision-1 draft while a second client saves revision 2 and the first client's query refetches; the original draft must still submit expected revision 1 and receive HTTP 409. Its draft is not silently rebased.
- API tests prove failed writes roll back the new snapshot, lines, pointer and counter without changing prior published contents; same-date replacements preserve every earlier revision.
- PostgreSQL 16 CI executes fresh install, populated 0001 → head upgrade, manual replacement and rollback; generated types must match exported OpenAPI in `pnpm check`.
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

Stage 1 local work may proceed after PostgreSQL 16 fresh/populated-upgrade tests, manual replacement/rollback, draft conflict behavior, and generated-contract freshness pass. These local checks passed on 2026-10-02; the DSQL path remains a separately gated package. **Production readiness additionally requires the expanded real S0.4 checks and the later feature-specific DSQL suite.**

**Implementation handoff:** link the actual commands, migration ledger, accepted decisions, fixture expectations, generated client procedure, and local/cloud evidence in the docs index. Stage 0 local prerequisites are now verified; Stage 1 delivery remains separate from this plan.
