# Staged implementation plan

**Status:** Stage 0 code through S0.6 delivered; local exit gate incomplete pending PostgreSQL 16 runtime verification and review fixes; live DSQL unverified | **Updated:** 2026-10-02
**Sequencing:** Stage 0 → Stage 1 deliver the local MVP **with Aurora DSQL compatibility designed in from the start**. Stage 2 and Stage 3 enrich it. Stage 4 (AWS) may be scheduled after Stage 1, but any production deployment **must** use Aurora DSQL, not RDS. Stage 5 (research) builds on reliable portfolio data with portable retrieval. See [`07-aurora-dsql-compatibility.md`](07-aurora-dsql-compatibility.md).

Each work package should produce a small PR or coherent series of PRs, include unit/integration/e2e tests where applicable, and be independently demonstrable. Prioritize a working vertical slice rather than creating empty abstractions for the entire future roadmap.

## Detailed execution plans

This roadmap defines stage scope, sequence, and exit gates. The companion plans expand each package into contracts, modules, fixtures, dependencies, implementation work, negative/retry cases, acceptance criteria, exclusions, and completion handoffs; they do not mark future work as implemented or authorize cloud provisioning.

| Stage | Execution plan |
| --- | --- |
| 0 — Local foundation | [Stage 0 implementation plan](stage-0-implementation-plan.md) |
| 1 — Portfolio MVP | [Stage 1 implementation plan](stage-1-implementation-plan.md) |
| 2 — Statement ingestion and personal finance | [Stage 2 implementation plan](stage-2-implementation-plan.md) |
| 3 — Tax lots, history and decision support | [Stage 3 implementation plan](stage-3-implementation-plan.md) |
| 4 — Optional AWS production deployment track | [Stage 4 implementation plan](stage-4-implementation-plan.md) |
| 5 — Portfolio-aware research and AI | [Stage 5 implementation plan](stage-5-implementation-plan.md) |

Use the roadmap's work-package number when selecting a task, then follow its `S`-prefixed package/subtasks in the companion plan. Stage 0–1 remain the local MVP; real DSQL checks remain independently required before production. Provider facts in the requirements retain their original verification dates and must be rechecked during integration work.

## Stage 0 — Local foundation

**Goal:** Reproducible React/FastAPI/PostgreSQL 16 local app, architected and documented for production DSQL; no paid services required to develop locally.

| Work package | Implementation tasks | Evidence of completion |
| --- | --- | --- |
| **0.1 Scaffold** | `apps/web` with React+TS+Vite; `services/api` with FastAPI and `uv`; Docker Compose PostgreSQL; `.env.example`; pinned lockfiles; basic run commands | `docker compose up` starts PostgreSQL/backend; Vite SPA loads; API `/health` returns success |
| **0.2 Dev quality** | Ruff, formatting, mypy or pyright, TS strict mode, ESLint, pytest, Vitest; PostgreSQL 16 CI service; generated OpenAPI/TypeScript freshness check | One-command lint/typecheck/test/build, generated-contract drift fails CI, and a failing test fails CI |
| **0.3 Schema core** | SQLAlchemy/Alembic migrations for accounts, securities/identifiers, issuer aliases, quotes and immutable position revisions; app UUID IDs, portable `NUMERIC`, DSQL-supported FKs/JSONB | Fresh and populated 0001 → head upgrades succeed on local PG16; fixture contains multiple accounts, effective dates, accepted/superseded snapshots and lines; DSQL plan/status are documented |
| **0.4 DSQL readiness spike** | `DatabaseEngineFactory` and official AWS SQLAlchemy dialect; DSQL migration runner contract; IAM/TLS config; bounded transaction/OCC retry helper | Small **real DSQL test cluster** successfully connects, creates/reads/writes minimal schema, executes schema migration and retry test when AWS access is provided. Until then report **DSQL unverified**, not production-ready. |
| **0.5 First end-to-end slice** | Account create/edit, ticker lookup from local seeded fixture, manual position entry, API-generated TS client | SPA adds a holding to account and retrieves it after reload |
| **0.6 Synthetic demo** | Fixture account, stocks, ETFs and cash; synthetic document fixtures for later import tests | A fresh clone demonstrates app entirely offline without secrets |

**Stage 0 local exit gate:** documented setup, passing PostgreSQL 16 fresh-install and populated-upgrade migrations/tests, manual replacement plus rollback, generated-contract freshness in CI, local migrations and offline manual-stock workflow. The populated upgrade must begin at the previous accepted schema with realistic accepted data (at least two accounts, multiple dates, distinct lines, and revisions/counters), then verify preservation and continued writes at head. Define and implement the DSQL dialect/migration path as a separately gated work package. A local MVP can proceed without AWS credentials; **no production-readiness claim until a real DSQL smoke/migration test passes**. No market API, PDF extraction or AI model is required.

**Stage 0.2 evidence (2026-10-01):** `pnpm check` runs lint, formatting, strict typechecks, 7 Vitest tests, 10 pytest tests, and the web production build. A temporary intentionally failing test caused the command to exit with status 1 and was removed afterward. The GitHub Actions workflow uses this same gate, but has not run remotely; Git initialization and a configured GitHub remote remain pending. DSQL remains unverified.

**Stage 0.3 implementation:** SQLAlchemy models and migrations `0001_core_portfolio_schema`–`0003_immutable_position_revisions_and_identifiers` define accounts, securities and scoped identifiers, issuers/aliases, dated quotes, and immutable position revisions with provenance. The opt-in PG16 suite now covers a fresh migration and populated `0002 → head` upgrade, legacy revision reconciliation, continued replacement, scoped identities and rollback. Original `0001`/`0002` files remain immutable. The latest migrations still require a successful PostgreSQL 16 CI run before this exit gate is complete; the earlier 0001-only PostgreSQL pass from 2026-10-01 is not current evidence.

**Stage 0.4 implementation (2026-10-02):** Added `DatabaseEngineFactory` for PostgreSQL and the official Aurora DSQL SQLAlchemy dialect, explicit scoped app/migration role settings, verified TLS and bounded pool settings, shared readiness probing, a checksummed 27-step DSQL migration plan across eight tables and seven asynchronous indexes, and bounded SQLSTATE/OCC retry in fresh sessions. The opt-in disposable-cluster suite covers migration, synthetic persistence, UUID/NUMERIC/JSONB/FK behavior, conflicting writes, immutable manual replacement/history/rollback, and scoped identities. The local suite passes; live populated-upgrade preservation and IAM reconnection after token expiry remain pending, so DSQL is unverified and production remains blocked. See `07-aurora-dsql-compatibility.md` for checked AWS/PyPI versions, limits and the migration/test commands.

**Stage 0.5 implementation (2026-10-02):** Added revision-aware account and dated manual-position API routes, local bounded security search, Pydantic validation and safe error responses, OpenAPI export plus generated TypeScript schema, and a keyboard-accessible TanStack Query entry/reload screen. Review follow-up adds immutable published position revisions, draft-bound base revisions, bounded arithmetic validation and PostgreSQL-backed CI. A background refresh must never advance a dirty draft's base revision. Same-date replacement appends a new snapshot and retains prior lines; an account pointer identifies the selected accepted revision. The original quality run had three database skips; offline Alembic SQL generation did not verify PostgreSQL runtime behavior. DSQL remains unverified.

## Stage 1 — Portfolio MVP (primary milestone)

### 1.1 Owned positions and valuation

- Add multiple accounts, manual stock/ETF/cash positions, typed validation, account filters and totals.
- Build canonical generic position-CSV upload + column-mapping preview + duplicate detection + transactionally applied **snapshot** semantics.
- Add quote provider interface with manual values and dated cached quote observations; integrate one optional free source after its usage rules are verified.
- Display missing/stale quotes and unpriced assets; do not mix currencies without available FX.

**Test:** Import the same account snapshot twice; quantities and NAV must not double. Switch to a later snapshot and preserve the prior one historically.

### 1.2 ETF composition ingestion

- Build import adapter interface (`fund identity`, `source`, `as_of`, `lines`, `completeness`).
- Implement **manual fund-CSV upload first**, then 2 official issuer full-holdings formats (suggest iShares IVV and SPDR SPY; Vanguard VOO after validation) using permitted access routes.
- Normalize CUSIP/ISIN/ticker-with-exchange and mark ambiguities; curate issuer mapping for share-class rollup.
- Persist immutable snapshots, source links, effective dates, parsing warnings and raw hashes. Use DSQL-compatible bounded batches, unpublished staging revisions and an atomic publication marker; test on both backends before cloud deployment.
- Add on-demand/daily-or-provider-appropriate refresh with cached fallback, rate awareness and parser regression fixtures.

**Test:** An issuer sample with one unmapped constituent must produce recognized and residual weights, not silently renormalize or drop that constituent.

### 1.3 Look-through calculations and dashboard

- Implement `Decimal` financial math for direct value + fund constituent weights by security and by optional issuer.
- Keep actual positions and look-through output separate; support account filters and top-N exposure ranking.
- Render holdings table, portfolio NAV, effective issuer/security exposure, per-account/fund drill-down and freshness/coverage badges.
- Add CSV export with calculation version, position/quote/fund-as-of and residual category.
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

**Stage 1 local exit gate / first release:** From a fresh local install, a user imports/enters ETFs plus direct stocks, refreshes/uploads dated compositions, and sees correct source-traceable consolidated exposure. Offline use works from cached/manual data. **Stage 1 production gate additionally requires real DSQL tests** for imports, same snapshot idempotency, schema, FK/index readiness, numeric math and concurrency retries.

## Stage 2 — Automated statement ingestion and personal finance

| Work package | Implementation tasks | Exit evidence |
| --- | --- | --- |
| **2.1 File pipeline** | Private FileStore; upload checks/hash; parse-status records; text PDF and CSV adapters; page/row evidence; review/commit through bounded staged batches and final publish | Re-importing same statement does not duplicate positions or transactions; partial batches are never visible |
| **2.2 Complex documents** | Docling OCR/table extraction and optional **local** Ollama schema-constrained interpretation; parser selection and manual correction | Synthetic scans/screenshots parsed into reviewable data; no silent commits |
| **2.3 Transactions** | Credit-card and bank transaction schemas, merchant/category rules, splits, refunds, transfers and duplicate handling | Credit-card payment and brokerage deposit are not double-counted as spending |
| **2.4 Finance dashboards** | Monthly income/spending, category trends, manual off-card expenses, balances and unified net worth | Reconcile category subtotals against canonical transaction total |
| **2.5 Optional account sync** | Evaluate Plaid sandbox, eligibility and institution coverage; read-only consent and encrypted token handling; no dependency on paid tiers | Manual/PDF workflow continues to function with sync disabled/expired |
| **2.6 Background jobs** | `JobStore`/`JobRunner` abstraction, local single-worker polling, optional SQS or tested optimistic DSQL lease in AWS; async document processing, retry/backoff, cancellation and status UI | At-least-once idempotent processing, DSQL OCC retry and safe failure recovery; no untested `SKIP LOCKED` dependency |

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

## Stage 4 — AWS production deployment track (Aurora DSQL required)

**Schedule optional after Stage 1, production database not optional.** Retain the full local PostgreSQL personal app. Do not deploy production against RDS PostgreSQL; DSQL compatibility tests start in Stage 0. The monthly DSQL free allowance does **not** cover the rest of the AWS stack.

- **4.1 Portable configuration:** same models/services; `DATABASE_BACKEND=postgres|aurora_dsql`; official DSQL SQLAlchemy dialect/connector, scoped IAM-based token-on-connect, `sslmode=verify-full`; PostgreSQL login stays local. Versioned migrations with one DSQL DDL statement per transaction and asynchronous index readiness checks. Use `FileStore(local|s3)`.
- **4.2 Infrastructure as code:** Terraform or AWS CDK. One single-region Aurora DSQL cluster (no multi-region replication); private S3 bucket for statement artifacts; S3+CloudFront for static React; low-cost FastAPI runtime (e.g., single EC2 or Lambda if measured compatible); least-privilege IAM and authenticated HTTPS app. Production's DSQL endpoint uses IAM+TLS, with optional separately billed PrivateLink if required. Avoid expensive default NAT/ALB/interface endpoints without a reason.
- **4.3 DSQL release gates:** Run real DSQL integration tests for migrations/FKs/index creation, UUID/NUMERIC/JSONB, IAM token refresh/pooled reconnect, portfolio aggregation, snapshot import batching and idempotency, optimistic-concurrency retry and job handling. Never label production-compatible based on PG-only tests.
- **4.4 Cost policy:** Track 100,000 free DPUs + 1 GB-month DSQL database storage (terms checked 2026-09-25), then **separately** forecast and budget API hosting, S3/CloudFront, logging, data transfer, optional SQS/PrivateLink, backup and storage overages. Budgets are not hard caps; confirm AWS account/region and eligibility.
- **4.5 Security and backups:** Fully authenticated application, private document storage, IAM non-admin DB user, TLS host verification, redacted logs, AWS Backup if budgeted, plus encrypted portable exports and tested local restore.
- **4.6 CI/CD:** Gate production promotion on the real DSQL test workflow and manual infrastructure/backup/budget approval. Keep routine PR tests local/offline to control cost.

**Stage 4 exit gate:** Securely access the app over HTTPS, import a synthetic statement to private S3, read and query **Aurora DSQL**, demonstrate an OCC retry and complete import without double-counting, restore/export data to local PG and shut down app resources cleanly. Confirm costs after promotional credits expire. Production uses DSQL, not RDS.

## Stage 5 — Portfolio-aware research and AI

- **5.1 Public data:** SEC EDGAR filings, XBRL fundamentals and official IR documents with dates/links; separate data-fetch adapters.
- **5.2 Research UI:** source-linked company summaries, period-over-period metrics with unit/period reconciliation, public-news search when an approved free provider is available.
- **5.3 Context:** calculate owned issuer exposure, account/fund sources, earnings/report history, user-written thesis and watchlist.
- **5.4 Retrieval:** Portable company/title/filing metadata search plus an abstract `ResearchIndex`; optional local PostgreSQL full-text/pgvector experiments must not become DSQL production dependencies. Evaluate a separate production search solution only if needed.
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
| Simple scheduling / provider-neutral job interface when needed | Untested DSQL locking assumptions, managed Redis, streaming architecture, Kubernetes |
| Document parsing rules and local review | Always-on remote AI, autonomous trading, wholesale agent frameworks |
| Verifiable source dates and residual exposure | Perfect breadth of ETFs, real-time quote promises, speculative classification |

**Next Codex prompt:** “Read `AGENTS.md` and all docs, especially `docs/07-aurora-dsql-compatibility.md`. Close the Stage 0 local exit gate: run the PostgreSQL 16 CI service through fresh install and a populated `0002 → head` upgrade, verify manual replacement/history and rollback, and confirm generated OpenAPI/TypeScript freshness. Keep DSQL marked unverified unless a real disposable cluster suite is run. Start Stage 1.1 only after the local gate passes; do not add later-stage imports, exposure, providers or AWS infrastructure speculatively.”
