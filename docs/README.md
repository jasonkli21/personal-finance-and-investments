# Personal Finance & Portfolio Intelligence — Docs

**Status:** Stage 0.3 core schema and PostgreSQL 16 migration verified; DSQL unverified
**Last reviewed:** 2026-10-01  
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

Stage 0.1 source and lockfiles are present. The web build, API tests, PostgreSQL 16 and API Compose startup, and Vite-to-API readiness proxy passed locally on 2026-10-01. Stage 0.2 adds Ruff, strict mypy, ESLint, Prettier, strict TypeScript, Vitest, and a shared `pnpm check` command. The local quality gate passed, and a temporary failing test confirmed that it exits unsuccessfully. Stage 0.3 adds SQLAlchemy/Alembic mappings and a PostgreSQL migration for issuers and aliases, accounts, securities, quotes, and owned position snapshots/lines. Its fresh migration and synthetic persistence/constraint checks passed on PostgreSQL 16 on 2026-10-01; `pnpm check` also passed. DSQL remains unverified; see the DDL plan in `07-aurora-dsql-compatibility.md`. The next planned work is **Stage 0 / Work Package 0.4** from `docs/05-roadmap.md`; work is paused after 0.3 at the user's request.

## Documentation maintenance

Treat all provider limits and free-tier claims as **time-sensitive**. Provider pricing, eligibility, redistribution rules, and institution support can change. When introducing a provider, add the official link, date checked, credentials needed, rate limits if confirmed, fallback behavior, and a fixture-backed integration test.
