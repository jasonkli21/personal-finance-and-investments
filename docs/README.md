# Personal Finance & Portfolio Intelligence — Docs

**Status:** Stage 0 local exit gate complete; Stage 1 local MVP complete; Stage 2 in progress; Stage 3 in progress; live DSQL unverified
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
| [`04-ingestion-and-ai.md`](04-ingestion-and-ai.md) | Finance parsing/validation/review, shared personal-AI extraction/research and privacy |
| [`adr/0001-shared-personal-ai.md`](adr/0001-shared-personal-ai.md) | Accepted AI ownership decision, handoff reconciliation, current seam and activation gaps |
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
| [`stage-3-release.md`](stage-3-release.md) | Actual Stage 3 package status, methodology choices, commands and verification limits |
| [`stage-4-implementation-plan.md`](stage-4-implementation-plan.md) | 4.1–4.6: optional authenticated AWS/DSQL deployment, cost gates, real-cluster tests and portable recovery |
| [`stage-5-implementation-plan.md`](stage-5-implementation-plan.md) | 5.1–5.6: public filings/facts, portfolio/thesis context, shared personal-AI retrieval and cited research and optional monitoring |

Task IDs follow roadmap packages (`S0.3` corresponds to 0.3); dotted subtask suffixes split a package into smaller slices. `S3.R` is the Stage 3 completion/evaluation task, not a new product stage. Dependency order takes precedence over numeric order. Stage 4 may follow Stage 1; research requires reliable portfolio data and only consumes later history/jobs when those features are available. Local completion never substitutes for the real-DSQL production gate.

Stage 1 was reviewed against Stage 0 commit `81b220e` on 2026-10-02. Its plan now specifies deterministic selection/financial policies, catalog creation from an empty database, review correction/cancellation, bounded atomic publication, durable frozen reports, private-input checks, and three major implementation commits (S1.1, S1.2, S1.3). The PostgreSQL 16 prerequisite and all three local packages are now delivered; [Stage 1 release evidence](stage-1-release.md) records observed checks, commands and limitations. The optional quote integration and credentialed production DSQL checks remain separate from local MVP completion.

## Product principles

1. **Look-through first.** Deliver a reliable consolidated company-exposure dashboard before expanding into a general finance suite.
2. **Local and free by default.** Manual entry, CSVs, synthetic fixtures, and local PostgreSQL must work with no external API keys or subscription. Production targets Aurora DSQL; its free database allowance does not make the whole stack free.
3. **Import, don't invent.** Track source, effective date, transformations, review status, and missing portions of all financial data.
4. **Keep actual and derived data separate.** Own one ETF share, not separately tradable shares of its constituents. Do not count constituent exposures as additional net worth.
5. **Predictable financial math.** Use decimal arithmetic, reconciliation tests, clear currencies, and deterministic calculation paths.
6. **Privacy before automation.** No personal statements sent to free cloud models by default; cloud use requires affirmative opt-in.
7. **Stage capabilities.** Prefer small, testable vertical slices to speculative abstractions or early infrastructure complexity.
8. **Shared AI, finance authority.** Finance owns its data, deterministic math, validation, workflows and UI; reusable AI capabilities integrate through personal-AI. Generic extraction, research, memory and model infrastructure are not duplicated here. Stage 1 has a disabled boundary only.
9. **One app, two SQL targets.** Use a DSQL-compatible schema and domain logic from the beginning; gate production releases on real DSQL migration and behavior tests.

## The critical user journey

1. Create brokerage/retirement accounts; add positions manually or import a brokerage CSV.
2. Supply or fetch dated holdings for supported ETFs; confirm ambiguous security identifiers.
3. View actual positions by account and a *separate* consolidated issuer/security look-through table.
4. Select a company such as NVIDIA and see direct value, each contributing ETF, total percentage of all assets, and the valuation/holdings dates.
5. Continue into PDF/screenshot imports, financial transactions, tax lots, scenario planning, and research in later stages.

**Stage 1 MVP ends after step 4.** Do not require PDF OCR, AI, bank connections, historical tax-lot accounting, or AWS for the first useful release. However, schema and persistence work must already comply with the production DSQL contract; paid cloud resources are not needed for every local PR.

## Source-of-truth hierarchy

- Delivered behavior: current code/OpenAPI and `stage-1-release.md`; future plans do not imply implemented capability. The integration handoff guides direction, with reconciled decisions in ADR 0001.
- Product behavior and scope: `01-product-spec.md`.
- Technical design: `02-architecture.md`; DSQL-specific decisions: `07-aurora-dsql-compatibility.md`.
- External-source claims and URLs: `03-data-sources.md`; reverify before implementation.
- Work sequencing and done criteria: `05-roadmap.md`.
- Security policy: `06-security-and-deployment.md` takes precedence over convenience.
- `AGENTS.md` gives Codex implementation instructions. In a conflict, flag it and reconcile docs before guessing.

## Current implementation and next task

Stage 1.1–1.3 is delivered at `f75e101`, `9053d1f`, and `0874f21`: reviewed CSV positions, generic/iShares CSV and SPDR XLSX fund compositions, dated manual/cached quotes, one-level exposure/issuer views and frozen report export. Stage 2 implementation is underway: private text-layer brokerage PDF preview, partial reviewed transaction and finance summaries, and local jobs are present; its remaining acceptance work is recorded in [Stage 2 release notes](stage-2-release.md). Stage 3 has delivered local S3.1 history/performance, S3.2 source-backed tax lots, and S3.3 read-only hypothetical lot-sale comparison; the remaining scope and verification limits are recorded in [Stage 3 release status](stage-3-release.md). The disabled `PersonalAIClient` seam remains inactive; no live upstream service calls occur. Historical checks below remain historical; see the Stage 1 release for its full-suite evidence.

Stage 0.1–0.6 code is present, including the local stack, SQLAlchemy/Alembic schema, DSQL boundary, manual account/position workflow, and explicit synthetic demo seeding. On 2026-10-02, `pnpm check` passed (8 Vitest, 48 pytest passed, 5 PostgreSQL/DSQL integration tests skipped, and a successful web build). The actual PostgreSQL 16.15 suite also passed (50 pytest passed, including fresh migration and populated `0002 → head` upgrade, replacement/history/rollback; 3 DSQL tests skipped). Those runs exposed and fixed the Alembic version-ledger width for the long 0003 revision ID. Stage 0's local exit gate is complete. The SQLite-backed browser transcript is in [`stage-0-demo-transcript.md`](stage-0-demo-transcript.md); SQLite is not PostgreSQL evidence. Live DSQL remains unverified and production-blocked.

## Documentation maintenance

Treat all provider limits and free-tier claims as **time-sensitive**. Provider pricing, eligibility, redistribution rules, and institution support can change. When introducing a provider, add the official link, date checked, credentials needed, rate limits if confirmed, fallback behavior, and a fixture-backed integration test.
