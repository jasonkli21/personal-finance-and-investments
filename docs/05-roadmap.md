# Staged implementation plan

**Status:** Stage 0–1 locally complete; Stage 2 partial; Stage 3 locally complete; Stage 4 tooling prepared; Stage 5 offline baseline; live Neon unverified | **Updated:** 2026-10-03
**Sequencing:** Stage 0 → Stage 1 deliver the local MVP with the preserved PostgreSQL finance behavior. Stage 2 and Stage 3 enrich it. Stage 4 (GCP) may be scheduled after Stage 1, using the current Neon PostgreSQL target. Stage 5 (research) builds on reliable portfolio data behind the separately gated shared personal-AI boundary. See [`07-postgres-neon.md`](07-postgres-neon.md).

The [shared-AI ADR](adr/0001-shared-personal-ai.md) governs later AI work: finance owns deterministic financial state/workflows; personal-AI owns reusable models, generic extraction, research/search, evidence retrieval and memory. The current disabled extraction seam does not implement Stage 2/5 or authorize service calls.

Each work package should produce a small PR or coherent series of PRs, include unit/integration/e2e tests where applicable, and be independently demonstrable. Prioritize a working vertical slice rather than creating empty abstractions for the entire future roadmap.

## Detailed execution plans

This roadmap defines stage scope, sequence, and exit gates. The companion plans expand each package into contracts, modules, fixtures, dependencies, implementation work, negative/retry cases, acceptance criteria, exclusions, and completion handoffs; they do not mark future work as implemented or authorize cloud provisioning.

| Stage | Execution plan |
| --- | --- |
| 0 — Local foundation | [Stage 0 implementation plan](stage-0-implementation-plan.md) |
| 1 — Portfolio MVP | [Stage 1 implementation plan](stage-1-implementation-plan.md) |
| 2 — Statement ingestion and personal finance | [Stage 2 implementation plan](stage-2-implementation-plan.md) |
| 3 — Tax lots, history and decision support | [Stage 3 implementation plan](stage-3-implementation-plan.md) |
| 4 — Optional GCP production deployment track | [Stage 4 implementation plan](stage-4-implementation-plan.md) |
| 5 — Portfolio-aware research and AI | [Stage 5 implementation plan](stage-5-implementation-plan.md) |

Use the roadmap's work-package number when selecting a task, then follow its `S`-prefixed package/subtasks in the companion plan. Stage 0–1 remain the local MVP; real Neon checks remain independently required before production. Provider facts in the requirements retain their original verification dates and must be rechecked during integration work.

## Stage 0 — Local foundation

**Goal:** Reproducible React/FastAPI/PostgreSQL 16 local app, architected and documented for production Neon PostgreSQL; no paid services required to develop locally.

| Work package | Implementation tasks | Evidence of completion |
| --- | --- | --- |
| **0.1 Scaffold** | `apps/web` with React+TS+Vite; `services/api` with FastAPI and `uv`; Docker Compose PostgreSQL; `.env.example`; pinned lockfiles; basic run commands | `docker compose up` starts PostgreSQL/backend; Vite SPA loads; API `/health` returns success |
| **0.2 Dev quality** | Ruff, formatting, mypy or pyright, TS strict mode, ESLint, pytest, Vitest; PostgreSQL 16 CI service; generated OpenAPI/TypeScript freshness check | One-command lint/typecheck/test/build, generated-contract drift fails CI, and a failing test fails CI |
| **0.3 Schema core** | Accounts, scoped identifiers, immutable positions, dated quotes and provenance in Alembic | Fresh and populated PostgreSQL upgrades preserve history and constraints |
| **0.4 Cloud database readiness** | Standard psycopg engine, verified Neon TLS, direct migration URL and bounded DB-only retries | Real Neon migration/reconnect/concurrency evidence required before production |
| **0.5 First end-to-end slice** | Account create/edit, ticker lookup from local seeded fixture, manual position entry, API-generated TS client | SPA adds a holding to account and retrieves it after reload |
| **0.6 Synthetic demo** | Fixture account, stocks, ETFs and cash; synthetic document fixtures for later import tests | A fresh clone demonstrates app entirely offline without secrets |

Production follows the [PostgreSQL/Neon contract](07-postgres-neon.md) and [GCP deployment plan](stage-4-implementation-plan.md). Ordinary local tests do not establish hosted readiness; prior provider-specific facts are preserved in the historical snapshot.

**Stage 0.3 implementation:** SQLAlchemy models and migrations `0001_core_portfolio_schema`–`0003_immutable_position_revisions_and_identifiers` define accounts, securities and scoped identifiers, issuers/aliases, dated quotes, and immutable position revisions with provenance. The opt-in PG16 suite now covers a fresh migration and populated `0002 → head` upgrade, legacy revision reconciliation, continued replacement, scoped identities and rollback. Original `0001`/`0002` files remain immutable. The updated migrations passed the real local PostgreSQL 16 gate on 2026-10-02; this is local evidence, not a remote CI run. See [release evidence](stage-1-release.md).

## Stage 1 — Portfolio MVP (primary milestone)

### 1.1 Owned positions and valuation

- Add multiple accounts, manual stock/ETF/cash positions, typed validation, account filters and totals.
- Build canonical generic position-CSV upload + column-mapping preview + duplicate detection + transactionally applied **snapshot** semantics.
- Add quote provider interface with manual values and dated cached quote observations; integrate one optional free source after its usage rules are verified.
- Display missing/stale quotes and unpriced assets; do not mix currencies without available FX.
- Provide reviewed local security/identifier/issuer catalog authoring so a fresh install works without demo data. Position imports target one account/date, require resolution of unmatched rows, and support correction/cancel with captured review revisions.

**Test:** Import the same account snapshot twice; quantities and NAV must not double. Switch to a later snapshot and preserve the prior one historically.

### 1.2 ETF composition ingestion

- Build import adapter interface (`fund identity`, `source`, `as_of`, `lines`, `completeness`).
- Implement **manual fund-CSV upload first**, then 2 official issuer full-holdings formats (suggest iShares IVV and SPDR SPY; Vanguard VOO after validation) using permitted access routes.
- Normalize CUSIP/ISIN/ticker-with-exchange and mark ambiguities; curate issuer mapping for share-class rollup.
- Persist immutable snapshots, source links, effective dates, parsing warnings and raw hashes. Use bounded PostgreSQL batches, unpublished staging revisions and an atomic publication marker; test locally and on Neon before cloud deployment.
- Add on-demand/daily-or-provider-appropriate refresh with cached fallback, rate awareness and parser regression fixtures.

**Test:** An issuer sample with one unmapped constituent must produce recognized and residual weights, not silently renormalize or drop that constituent.

### 1.3 Look-through calculations and dashboard

- Implement `Decimal` financial math for direct value + fund constituent weights by security and by optional issuer.
- Keep actual positions and look-through output separate; support account filters and top-N exposure ranking.
- Render holdings table, portfolio NAV, effective issuer/security exposure, per-account/fund drill-down and freshness/coverage badges.
- Add CSV export with calculation version, position/quote/fund-as-of and residual category.
- Freeze report inputs (including issuer mappings/policies), results and filters durably under one calculation identity; pagination, drill-down and CSV remain consistent after new data and server restart. Incomplete totals and unsupported signed allocations never imply complete portfolio percentages.
- Add Playwright demo from manual portfolio + uploaded ETF files to total-exposure drill-down.

**Golden acceptance fixture:**

| Holding | Value | NVDA effective weight |
| --- | ---: | ---: |
| NVDA directly owned | $30,000 | 100% |
| ETF A | $50,000 | 8% |
| ETF B | $20,000 | 6% |
| Other investments | $100,000 | 0% |
| **Total NAV** | **$200,000** | |

Expected NVDA look-through: `$30,000 + ($50,000 × 0.08) + ($20,000 × 0.06) = $35,200`, or `17.6% of NAV`. **Owned NAV remains $200,000**; no ETF constituents create new positions. An ETF with no current composition still counts toward NAV and appears in unclassified exposure.

**Stage 1 local exit gate / first release:** From a fresh local install, a user imports/enters ETFs plus direct stocks, refreshes/uploads dated compositions, and sees correct source-traceable consolidated exposure. Offline use works from cached/manual data. **Stage 1 production gate additionally requires real Neon tests** for imports, same snapshot idempotency, schema, FK/index correctness, numeric math and concurrency retries.

The reviewed [Stage 1 plan](stage-1-implementation-plan.md#review-decisions-and-implementation-handoff) fixes selection, review, financial and safety policies and groups delivery into one coherent commit for each major package **1.1, 1.2 and 1.3**. Prerequisite Stage 0 gate fixes may have their own commit. Two official-format parsers remain mandatory; an official-download/upload route is acceptable when current evidence does not permit automatic retrieval. Optional quote integration and unexecuted cloud checks must be documented honestly rather than silently promoted to release dependencies.

## Stage 2 — Automated statement ingestion and personal finance

| Work package | Implementation tasks | Exit evidence |
| --- | --- | --- |
| **2.1 File pipeline** | Private FileStore; upload checks/hash; parse-status records; text PDF and CSV adapters; page/row evidence; review/commit through bounded staged batches and final publish | Re-importing same statement does not duplicate positions or transactions; partial batches are never visible |
| **2.2 Complex documents** | Shared generic OCR/structured candidate extraction via `PersonalAIClient`; finance evidence/schema/arithmetic review, deterministic templates and manual fallback | Synthetic scans/screenshots parsed into reviewable data; no silent commits |
| **2.3 Transactions** | Credit-card and bank transaction schemas, merchant/category rules, splits, refunds, transfers and duplicate handling | Credit-card payment and brokerage deposit are not double-counted as spending |
| **2.4 Finance dashboards** | Monthly income/spending, category trends, manual off-card expenses, balances and unified net worth | Reconcile category subtotals against canonical transaction total |
| **2.5 Optional account sync** | Evaluate Plaid sandbox, eligibility and institution coverage; read-only consent and encrypted token handling; no dependency on paid tiers | Manual/PDF workflow continues to function with sync disabled/expired |
| **2.6 Background jobs** | Durable DB rows, leases, cancellation and fencing; bounded Cloud Run execution in cloud | Idempotency, reclaim, stale-worker rejection and recovery tested; hosted execution separately gated |

**Stage 2 exit gate:** Upload at least one synthetic brokerage statement and one synthetic bank/card statement, review extraction and reconcile holdings/spending; demonstrate a local-only/no-AI fallback. Keep OCR accuracy benchmark results with test fixtures.

## Stage 3 — Tax lots, history and decision support

| Work package | Implementation tasks | Exit evidence |
| --- | --- | --- |
| **3.1 Historical performance** | Historical position/price records, transfers, dividends, corporate actions, contributions/withdrawals; documented TWR/MWR scopes | Returns do not mistake deposits for market gains |
| **3.2 Tax lots** | Import lots from CSV/Plaid when supplied; lot evidence, adjustment events, unverifiable/missing flags | Aggregate basis is never assumed to imply individual lots |
| **3.3 Sale simulator** | Share/amount target; explicit lot selection; short/long holding periods; estimated taxable gain/loss; potential wash-sale warnings | Simulation does not mutate actual position state or submit orders |
| **3.4 Portfolio simulation** | Hypothetical buys/sells; estimated exposure, overlap, cash, allocation drift; optional thematic tags | Before/after look-through sums reconcile within tolerances |
| **3.5 Planning** | Income, dividend trends, investment cash runway, large purchase scenarios | Assumptions and uncertainty are clearly surfaced |

**Stage 3 exit gate:** With synthetic purchase lots of varying bases, compare two hypothetical share-sale selections and see different realized gains, unchanged actual owned holdings, and resulting hypothetical post-trade exposure. Flag missing lots and cross-account wash-sale risks without asserting tax certainty.

## Stage 4 — Optional GCP / Neon deployment

The local application remains usable indefinitely. Production uses Neon PostgreSQL via the same SQLAlchemy/psycopg and Alembic path.

- **4.1 Configuration/storage/auth:** runtime DATABASE_URL, optional direct MIGRATION_DATABASE_URL, verified TLS and bounded pools; FileStore(local|gcs). Preserve OIDC/PKCE, revocable sessions, HTTPS cookies and origin/CSRF checks.
- **4.2 Infrastructure:** Cloud Run API and bounded worker Job, Firebase Hosting SPA and same-origin /api routing, private GCS, Artifact Registry, Secret Manager and scoped service identities. No automatic provisioning.
- **4.3 Real cloud gate:** fresh/populated Alembic migration, runtime reconnect and concurrent publication/retry using a disposable Neon branch; authenticated HTTPS and private GCS evidence.
- **4.4 Costs:** review target GCP and separate Neon billing, scaling/connections/storage/log retention and alerts. Alerts are not hard spending caps.
- **4.5 Recovery:** encrypted portable export from Neon/GCS and isolated PostgreSQL restore; scope, tamper, retention and RPO/RTO evidence.
- **4.6 Release:** immutable image/source/schema/configuration-bound evidence, operations rehearsal and explicit production approval. Ordinary CI remains local/offline.

Tooling is prepared; no credentialed hosted result or deployed real-data safety is claimed. See the [Stage 4 plan](stage-4-implementation-plan.md), [release](stage-4-release.md), and [migration audit](gcp-neon-migration.md).

## Stage 5 — Portfolio-aware research and AI

- **5.1 Public data:** SEC/IR research observations via shared evidence capabilities; finance validates issuer/period/unit and retains dated source references. Add only necessary finance-specific deterministic fact adapters.
- **5.2 Research UI:** shared cited research via `PersonalAIClient`, finance citation/result checks and deterministic period-over-period metrics; generic search/provider orchestration stays upstream.
- **5.3 Context:** calculate owned issuer exposure, account/fund sources, earnings/report history, user-written thesis and watchlist.
- Use the PostgreSQL/Neon contract and GCP deployment gates; retain bounded, idempotent writes and all finance review/provenance invariants.
- **5.5 Monitoring:** optional scheduled *public* developments and saved research snapshots; user chooses notifications, no order execution.
- **5.6 Evaluate:** synthetic and public-company test set for citation fidelity, stale news, irrelevant retrieval, unsupported claims and model/provider outages.

**Stage 5 exit gate:** Choose a portfolio company, produce a dated research summary with links to accessible source documents, distinguish published facts from inferences, and show source-based effective exposure. The app remains usable when every model/search API is disabled.

## Cross-cutting done checklist for every PR

- [ ] Implements a scoped work package, not speculative future infrastructure.
- [ ] Database migrations and OpenAPI contracts updated if interfaces changed.
- [ ] No real bank statements, account identifiers or vendor secrets in committed tests/logs.
- [ ] Unit/integration tests cover nominal case, missing data, duplicate/retry and failure path.
- [ ] Imported/external data has effective date, retrieval date, provenance and quality indicators.
- [ ] No paid provider required or automatically selected; offline fixture path works for core portfolio features.
- [ ] User-visible financial totals reconcile or explicitly expose residual/unpriced/unconverted portions.
- [ ] Relevant docs updated and commands tested on a clean local setup.

## Backlog ordering and scope control

| Do first | Only when justified |
| --- | --- |
| Manual positions, CSV importer, cached quote/manual price, 2 ETF adapters, derived exposure | Brokerage-link onboarding and unsupported instruments |
| SQL + FastAPI REST and generated TS client | Microservices, a second operational datastore or general event bus |
| Durable Finance job rows and bounded same-codebase workers | New queue or scheduling infrastructure only after a demonstrated requirement |
| Document parsing rules and local review | Always-on remote AI, autonomous trading, wholesale agent frameworks |
| Verifiable source dates and residual exposure | Perfect breadth of ETFs, real-time quote promises, speculative classification |

Production follows the [PostgreSQL/Neon contract](07-postgres-neon.md) and [GCP deployment plan](stage-4-implementation-plan.md). Ordinary local tests do not establish hosted readiness; prior provider-specific facts are preserved in the historical snapshot.


Provider-specific dated delivery facts are preserved in [the pre-migration snapshot](history/pre-gcp-neon/05-roadmap.md). [ADR 0002](adr/0002-gcp-neon.md) and the [migration record](gcp-neon-migration.md) define the current architecture; this plan does not claim additional product completion.
