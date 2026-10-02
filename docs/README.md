# Personal Finance & Portfolio Intelligence — Docs

**Status:** Stage 0 local foundation through S0.6 implemented; live DSQL unverified
**Last reviewed:** 2026-10-02
**Databases:** PostgreSQL 16 local/personal; Aurora DSQL required for production  
**Deployment:** local indefinitely; AWS deployment optional until ready, with production targeting DSQL  
**Cost target:** zero recurring charges for the local MVP; no automatic use of paid API tiers

## Product in one paragraph

A private tool to track stocks, ETFs, cash, and eventually broader personal finances across accounts. Its differentiating feature is **consolidated look-through exposure**: combine directly owned companies with the holdings embedded in ETFs and show each company's total dollar/percentage exposure, constituent funds, and source freshness. Evolve into document-assisted imports, transaction categorization, tax-lot planning, portfolio simulation, and portfolio-aware AI research. The application is decision support—not a broker, automated trading system, tax preparer, or source of personalized investment advice.

## Document map

| File | Audience / purpose |
| --- | --- |
| [`../AGENTS.md`](../AGENTS.md) | Codex's working rules and implementation guardrails |
| [`01-product-spec.md`](01-product-spec.md) | Product goals, scope, journeys, requirements, acceptance criteria, non-goals |
| [`02-architecture.md`](02-architecture.md) | TypeScript/Python stack, local PostgreSQL + production DSQL, conceptual schema, API and repo layout |
| [`03-data-sources.md`](03-data-sources.md) | Free-first market, ETF, account, regulatory, and research data; provenance and current limits |
| [`04-ingestion-and-ai.md`](04-ingestion-and-ai.md) | Deterministic parsing, OCR, optional local/cloud LLMs, evaluation and privacy |
| [`05-roadmap.md`](05-roadmap.md) | Stages 0–5 with implementable work packages, dependencies, exit gates, and MVP cut line |
| [`06-security-and-deployment.md`](06-security-and-deployment.md) | Local security, AWS/DSQL deployment, cost gates, backups and migration |
| [`07-aurora-dsql-compatibility.md`](07-aurora-dsql-compatibility.md) | **Mandatory production compatibility contract:** DSQL features/limits, IAM, migration, batching, research and testing |

## Stage implementation plans

The plans below expand the roadmap into execution backlogs using the phase-plan structure in `personal-ai-system/docs`: scope boundaries, delivery conventions, verification matrices, required contracts/artifacts, dependency maps, task goals/work/requirements/acceptance criteria, and completion reviews. They are plans, not evidence of delivered capabilities. The source-of-truth hierarchy below still applies.

| Plan | Coverage / first demonstrable slice |
| --- | --- |
| [`stage-0-implementation-plan.md`](stage-0-implementation-plan.md) | 0.1–0.6: local tooling/schema, DSQL boundary, account → manual holding → reload |
| [`stage-1-implementation-plan.md`](stage-1-implementation-plan.md) | 1.1–1.3: reviewed position/fund CSVs, valuation, reconciled exposure and export; first local MVP |
| [`stage-2-implementation-plan.md`](stage-2-implementation-plan.md) | 2.1–2.6: private statement review, OCR/local fallback, transactions, finance, optional sync and durable jobs |
| [`stage-3-implementation-plan.md`](stage-3-implementation-plan.md) | 3.1–3.5: history/returns, supplied tax lots, hypothetical sale/exposure and planning comparisons |
| [`stage-4-implementation-plan.md`](stage-4-implementation-plan.md) | 4.1–4.6: optional authenticated AWS/DSQL deployment, cost gates, real-cluster tests and portable recovery |
| [`stage-5-implementation-plan.md`](stage-5-implementation-plan.md) | 5.1–5.6: public filings/facts, portfolio/thesis context, portable retrieval, cited research and optional monitoring |

Task IDs follow roadmap packages (`S0.3` corresponds to 0.3); dotted subtask suffixes split a package into smaller slices. `S3.R` is the Stage 3 completion/evaluation task, not a new product stage. Dependency order takes precedence over numeric order. Stage 4 may follow Stage 1; research requires reliable portfolio data and only consumes later history/jobs when those features are available. Local completion never substitutes for the real-DSQL production gate.

## Product principles

1. **Look-through first.** Deliver a reliable consolidated company-exposure dashboard before expanding into a general finance suite.
2. **Local and free by default.** Manual entry, CSVs, synthetic fixtures, and local PostgreSQL must work with no external API keys or subscription. Production targets Aurora DSQL; its free database allowance does not make the whole stack free.
3. **Import, don't invent.** Track source, effective date, transformations, review status, and missing portions of all financial data.
4. **Keep actual and derived data separate.** Own one ETF share, not separately tradable shares of its constituents. Do not count constituent exposures as additional net worth.
5. **Predictable financial math.** Use decimal arithmetic, reconciliation tests, clear currencies, and deterministic calculation paths.
6. **Privacy before automation.** No personal statements sent to free cloud models by default; cloud use requires affirmative opt-in.
7. **Stage capabilities.** Prefer small, testable vertical slices to speculative abstractions or early infrastructure complexity.
8. **One app, two SQL targets.** Use a DSQL-compatible schema and domain logic from the beginning; gate production releases on real DSQL migration and behavior tests.

## The critical user journey

1. Create brokerage/retirement accounts; add positions manually or import a brokerage CSV.
2. Supply or fetch dated holdings for supported ETFs; confirm ambiguous security identifiers.
3. View actual positions by account and a *separate* consolidated issuer/security look-through table.
4. Select a company such as NVIDIA and see direct value, each contributing ETF, total percentage of all assets, and the valuation/holdings dates.
5. Continue into PDF/screenshot imports, financial transactions, tax lots, scenario planning, and research in later stages.

**Stage 1 MVP ends after step 4.** Do not require PDF OCR, AI, bank connections, historical tax-lot accounting, or AWS for the first useful release. However, schema and persistence work must already comply with the production DSQL contract; paid cloud resources are not needed for every local PR.

## Source-of-truth hierarchy

- Product behavior and scope: `01-product-spec.md`.
- Technical design: `02-architecture.md`; DSQL-specific decisions: `07-aurora-dsql-compatibility.md`.
- External-source claims and URLs: `03-data-sources.md`; reverify before implementation.
- Work sequencing and done criteria: `05-roadmap.md`.
- Security policy: `06-security-and-deployment.md` takes precedence over convenience.
- `AGENTS.md` gives Codex implementation instructions. In a conflict, flag it and reconcile docs before guessing.

## Current implementation and next task

Stage 0.1 source and lockfiles are present. The web build, API tests, PostgreSQL 16 and API Compose startup, and Vite-to-API readiness proxy passed locally on 2026-10-01. Stage 0.2 adds Ruff, strict mypy, ESLint, Prettier, strict TypeScript, Vitest, and a shared `pnpm check` command. Stage 0.3 adds SQLAlchemy/Alembic mappings and a PostgreSQL migration for issuers and aliases, accounts, securities, quotes, and owned position snapshots/lines. Stage 0.4 adds a separate official DSQL engine, checksummed/resumable migration runner, IAM/TLS configuration, bounded OCC retry, and an explicitly gated real-cluster suite. Stage 0.5 adds account and manual-position routes, revision-safe replacements, OpenAPI-generated TypeScript schemas, and the local entry/reload UI. Stage 0.6 adds explicit demo-mode seeding, stable synthetic rows, reset protection, fixture files, and handoff documentation. The 2026-10-02 local gate passed (7 Vitest, 37 pytest, web build); the SQLite-backed browser transcript is in [`stage-0-demo-transcript.md`](stage-0-demo-transcript.md). One PostgreSQL and two DSQL database tests remained skipped; live DSQL remains unverified. Next is **Stage 1**, beginning with the packages in [`stage-1-implementation-plan.md`](stage-1-implementation-plan.md).

## Documentation maintenance

Treat all provider limits and free-tier claims as **time-sensitive**. Provider pricing, eligibility, redistribution rules, and institution support can change. When introducing a provider, add the official link, date checked, credentials needed, rate limits if confirmed, fallback behavior, and a fixture-backed integration test.
