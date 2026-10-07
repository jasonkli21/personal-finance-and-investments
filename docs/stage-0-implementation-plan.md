# Stage 0 implementation plan

**Current implementation status:** see [current state](current-state.md).
**Updated:** 2026-10-03 (provider migration; original delivery dates retained)
**Roadmap coverage:** Work packages 0.1–0.6

This is the execution plan for the local foundation: a reproducible application with a persisted manual holding and an independently testable production database boundary. Use [the docs router](README.md) to load the product or database contracts relevant to the selected work package. Those requirements take precedence over proposed implementation names here.

The structure follows the phase plans in `personal-ai-system/docs`: scope, contracts, dependency ordering, independently demonstrable tasks, and a completion review. It adapts their delivery discipline to this application's SQL, financial arithmetic, and privacy requirements.

## Scope boundary

Stage 0 includes:

- React/TypeScript/Vite and FastAPI scaffolding, local PostgreSQL 16, lockfiles, and developer commands.
- Offline lint, formatting, type checking, tests, and non-deploying CI.
- Portable accounts, securities/issuers/identifiers, quotes, and position-snapshot persistence.
- Keep one standard PostgreSQL engine, canonical Alembic migrations and bounded DB-only retries; require real Neon evidence before cloud promotion.
- Account create/edit, local security lookup, manual holding entry, and retrieval after reload.
- An opt-in, synthetic, repeatable offline demo.

The smallest vertical slice is **create account → select seeded equity → enter quantity and dated manual price → reload persisted holding**. Affected modules are `accounts`, `securities`, `portfolio`, `prices`, database configuration, and the web API boundary.

CSV imports, ETF parsers/decomposition, PDF/OCR, AI, spending, tax lots, workers, authentication for remote hosting, and cloud application infrastructure are outside this stage. Neon tests are a readiness exercise, not permission to launch production.

Historical delivery notes below reflect the environment at each recorded run; the later Stage 0 PostgreSQL exit evidence and Stage 1 release supersede earlier “unverified locally” statements. The [shared-AI ADR](adr/0001-shared-personal-ai.md) reconciles future integration direction without changing this delivered foundation.

## Delivery conventions and cross-cutting requirements

- Review existing work before implementing a package. The docs index records 0.1 and 0.2; do not recreate tooling or treat uncommitted schema work as accepted delivery.
- Keep FastAPI handlers thin and domain logic outside routes. Current S0.5 domain functions receive a SQLAlchemy `Session` directly; a separate repository-object layer is not implemented. Treat this as the documented Stage 0 persistence convention until Stage 1 demonstrates a need for repositories. Only database modules know engine-specific SQL or authentication behavior.
- Generate UUIDs in application code. Persist authoritative financial values as `NUMERIC` and process them as `Decimal`; choose and document precision, scale, overflow, and rounding policy.
- Use UTC instants for recording/retrieval timestamps and explicit dates for statement-effective dates. Preserve currency and the meaning of each timestamp.
- Financial decimals cross the API as strings. The web may format them, but never calculates authoritative balances with JavaScript floating point.
- Keep one standard PostgreSQL engine, canonical Alembic migrations and bounded DB-only retries; require real Neon evidence before cloud promotion.
- Local settings bind published services to loopback. No credentials or private data belong in fixtures, logs, `.env.example`, or frontend bundles.
- No external API/model is required. A real Neon result requires a real cluster; compilation, mocks, and PostgreSQL tests have distinct labels.

## Required verification matrix

| Surface | Required local evidence | Neon evidence / gating |
| --- | --- | --- |
| Bootstrap | Locked install, Compose readiness, SPA/API proxy | Not required for scaffold |
| Quality gate | Lint, formatting, strict types, backend/web tests, build; intentional failure detection; OpenAPI and generated TypeScript must match committed outputs | No cloud dependency in routine CI |
| Core schema | PostgreSQL 16 fresh install and populated 0001 → head upgrade; fixture contains at least two accounts, multiple dates, accepted/superseded snapshots and lines; UUID/NUMERIC/JSONB/FK/uniqueness cases | Real create/upgrade and index-correctness test before production |
| Transactions | Rollback, safe batch bounds, injected retry/exhaustion | Real conflicting writes with bounded full-unit retry |
| Connection lifecycle | Invalid config and session cleanup | Verified TLS, pooled/direct endpoints, reconnect and bounded connections |
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

Preserve application UUIDs, Decimal/NUMERIC, scoped identifiers and immutable revisions. Use short DB-only transactions and bounded retries for PostgreSQL serialization/deadlock failures. Local validation and real Neon promotion evidence are separate.

**Required configuration and API contract:**

| Boundary | Required behavior |
| --- | --- |
| `DATABASE_BACKEND` | Only `postgres`; one standard SQLAlchemy/psycopg engine |
| PostgreSQL configuration | Local database URL, bounded connection pool, no remote/public defaults |
| Cloud connection configuration | `DATABASE_URL` with verified Neon TLS; optional direct `MIGRATION_DATABASE_URL`; Alembic is the sole schema history |
| Feature/cost settings | Remote AI/account sync/paid fallback disabled; optional provider configuration must not break local boot |
| `GET /health` | Existing liveness contract; preserve existing readiness semantics separately |
| `/api/v1/accounts` | Create/list; `PATCH /{id}` edits or archives account metadata |
| `/api/v1/securities/resolve?q=` | Bounded local lookup; ambiguous/unknown result is explicit |
| `/api/v1/accounts/{id}/positions` | Get/replace manual snapshot with expected revision; no trade semantics |

Finalize exact schemas in OpenAPI before connecting UI. Include safe errors for malformed input, missing resources, stale revisions, and unavailable storage; never return ORM or driver exceptions.

## Dependency map

```text
S0.1 Scaffold -> S0.2 Quality -> S0.3 Schema -> S0.4 PostgreSQL boundary
                                                 -> S0.5 Manual API/UI -> S0.6 Demo
S0.4 real Neon evidence -------------------------> production readiness
S0.3 + S0.5 + S0.6 local evidence ---------------> Stage 1 local development
```

S0.4 has a local contract/tooling deliverable and a separate credentialed execution gate. Missing cloud access does not block the local MVP; it leaves Neon unverified.

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
- The lockfiles and environment example contain no secrets; local startup requires no cloud/model credentials.

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
- Keep one standard PostgreSQL engine, canonical Alembic migrations and bounded DB-only retries; require real Neon evidence before cloud promotion.

**Requirements:** app UUIDs; documented `NUMERIC` precision; parameterized SQL; constrained relationships and scoped identifiers; bounded JSON metadata; no triggers, extension types, implicit generated IDs, or future spending/tax/research tables.

**Acceptance criteria:**

- Fresh migrations and a populated 0001 → head upgrade succeed on actual PostgreSQL 16. The populated fixture has multiple accounts, several effective dates, accepted and superseded snapshots, lines, identifiers and aliases; after upgrade, verify all prior content, revision selection, counters, uniqueness and a successful subsequent replacement.
- Constraints reject invalid references and duplicate scoped identities. Identifier identity is scoped by namespace/exchange/value; issuer aliases retain namespace and review status, and cross-issuer collisions remain detectable as ambiguity.
- Decimal quantities/prices round-trip without float conversion; zero quantities and unresolved identifiers are preserved.
- Two accounts holding the same security remain independent; failed replacement leaves the previous snapshot selected.
- Keep one standard PostgreSQL engine, canonical Alembic migrations and bounded DB-only retries; require real Neon evidence before cloud promotion.

**Out of scope:** assuming ORM DDL compilation proves PostgreSQL compatibility; full ETF/import schemas; migration of real user data.

### S0.4 — PostgreSQL connection and transaction boundary

**Gate:** cloud promotion requires real Neon verification; see [current state](current-state.md) for delivery evidence.
**Modules:** config, db/engine.py, db/urls.py, db/transactions.py, Alembic.

Use one standard psycopg engine with bounded pools, pre-ping, connect timeout and verified TLS for Neon. DATABASE_URL selects runtime; optional MIGRATION_DATABASE_URL selects a direct migration connection. Alembic is the only migration history. Never edit applied revisions. Test fresh and populated upgrades, Decimal/UUID/JSONB/FK behavior, immutable revisions and real concurrent publication. The retry helper repeats only bounded DB work after PostgreSQL serialization/deadlock failures; external work stays outside retries. Credentialed disposable Neon migration/reconnect/concurrency checks remain distinct from local evidence. See [the database contract](07-postgres-neon.md).

The original S0.4 provider spike and dated local delivery runs are preserved in [historical evidence](history/pre-gcp-neon/stage-0-implementation-plan.md). They are not pending work on a second dialect.

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
- Keep one standard PostgreSQL engine, canonical Alembic migrations and bounded DB-only retries; require real Neon evidence before cloud promotion.

**Requirements:** no institution/account information copied from real statements; seeding performs no downloads or model calls; source dates and synthetic labels are visible. Do not enable demo/reset commands implicitly in production.

**Acceptance criteria:**

- A fresh local environment demonstrates the slice with no secrets/provider signup.
- Re-running the seed does not duplicate accounts, securities, quotes, or holdings.
- Documented expected totals match the persisted fixture, including cash counted once.
- Completion evidence distinguishes historical recorded checks from checks actually rerun for this delivery.

**Out of scope:** pretending synthetic ETFs have verified issuer holdings, OCR benchmarking, or cloud provisioning.

## Stage 0 completion review

Before declaring the **local** foundation complete, verify all local acceptance criteria and answer:

1. Can a clean checkout start, migrate, test, and demonstrate a persisted manual holding offline?
2. Are financial values decimal, dated, currency-labelled, and attributable?
3. Are snapshots distinct from trades and accounts isolated from one another?
4. Does the API generate the web contract, with safe validation/conflict errors?
5. Are migrations append-only, and do retries use fresh DB-only transactions?
6. Is live Neon evidence either recorded accurately or clearly marked unverified?

Preserve application UUIDs, Decimal/NUMERIC, scoped identifiers and immutable revisions. Use short DB-only transactions and bounded retries for PostgreSQL serialization/deadlock failures. Local validation and real Neon promotion evidence are separate.

**Implementation handoff:** link the actual commands, migration ledger, accepted decisions, fixture expectations, generated client procedure, and local/cloud evidence in the docs index. Stage 0 local prerequisites are now verified; Stage 1 delivery remains separate from this plan.


Provider-specific dated delivery facts are preserved in [the pre-migration snapshot](history/pre-gcp-neon/stage-0-implementation-plan.md). [ADR 0002](adr/0002-gcp-neon.md) and the [migration record](gcp-neon-migration.md) define the current architecture; this plan does not claim additional product completion.
