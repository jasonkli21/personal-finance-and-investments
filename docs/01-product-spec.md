# Product specification

**Current implementation status:** [docs/current-state.md](current-state.md) | **Requirements updated:** 2026-10-03 | **MVP:** Stage 1

The finance app owns financial state, deterministic calculations/validation, workflows and UI. Reusable AI extraction, research/search and attributable preference memory integrate through `personal-ai-system`; they do not replace finance records. See [the ownership ADR](adr/0001-shared-personal-ai.md). The implemented research baseline uses manual source references and deterministic calculations; live AI transport remains disabled. The [documentation index](README.md) links the release evidence for each stage; this specification also includes future requirements. The [maintainability review](maintainability-review.md) records current implementation gaps.

## 1. Problem and product promise

A brokerage dashboard typically shows instruments owned *directly*; it may not provide consolidated exposure to the same companies through multiple ETFs or accounts. Keeping positions, expense transactions and purchase lots current can also require repetitive imports or navigation. This product offers one private, explainable place to answer:

- What do I **actually hold**, in each account, at a stated date/price?
- How much economic exposure do I have to **each security and issuer**, including ETF constituents?
- Which ETFs overlap, and how much of my allocation is unresolved or out of date?
- Later: where does my money go, which purchase lots might I sell, and how would a hypothetical trade change exposures or estimated gains?
- Later still: how do new disclosures and research relate to **my existing** holdings and investment thesis?

The initial user is a single, technically comfortable investor using the app privately. Multi-user household collaboration and commercial SaaS features are out of scope until intentionally reconsidered.

## 2. Release tiers

| Area | Stage 1 — MVP | Stage 2 | Stage 3 | Stage 5 |
| --- | --- | --- | --- | --- |
| Holdings | Manual entry/edit/delete; CSV position import; multiple accounts; stocks/ETFs/cash | PDF/screenshot imports; optional read-only connection | Historical snapshots, transaction-based reconciliation | Research context |
| ETF exposure | Supported issuer full holdings and manual holdings CSV; issuer/security rollups; residual/unclassified | Additional ETF formats, nested funds when reliable | Overlap analysis, temporal exposure, thematic groups | Portfolio-aware research |
| Valuation | Dated quotes; manual price fallback; displayed staleness | Scheduled refreshes | Performance, contributions, dividends | Event-aware commentary |
| Spending | Not in MVP | Statement import, categories, edits, transfer matching, cash flow | Runway and large-purchase scenarios | Optional research-generated explanations |
| Tax lots | Not in MVP | Import schema can preserve provided lot fields | Lot view, sale planning, holding period, estimated gains, warnings | Optional event context |
| AI | Not required | Optional candidate extraction via personal-AI; deterministic/manual fallback | None required | Cited research, monitoring, searchable notes |
| Deployment | Local PostgreSQL 16 | Local PostgreSQL 16 | Local PostgreSQL 16 | Local PostgreSQL or production Neon PostgreSQL |

Stage 4 is an **optional deployment track** in timing, but the production database choice is **Neon PostgreSQL**, not RDS PostgreSQL. Database-compatible modeling and smoke tests begin in Stage 0; the complete product remains available locally with PostgreSQL. See [`07-postgres-neon.md`](07-postgres-neon.md).

## 3. Stage 1 user stories and acceptance criteria

### P1 — Manage accounts and owned positions [MUST]

- Create, rename, archive accounts; mark account type (taxable/retirement/cash/other) and base currency.
- Add, edit, or delete a position in an account with security, quantity, and as-of date; hold cash as cash, not a fake ticker.
- Support decimal/fractional quantities, zero positions, and explicit manual prices for unquoted instruments.
- Show actual owned value and subtotals per account, with as-of date and last price source.
- Do not imply manual position snapshots establish historical purchase cost, tax lots, or performance.

**Accept when:** Creating two accounts with the same ticker yields two independent owned positions; editing or removing one does not mutate the other; cash is counted once.

### P2 — Import positions from CSV [MUST]

- Provide a canonical CSV template and one generic mapping workflow: `account`, `ticker/identifier`, `quantity`, optional `price`, `currency`, `as_of`.
- Map CSV columns interactively; preview rows before applying; surface unknown securities and conflicts.
- Treat each accepted file as an **account/date position snapshot**, not additional purchases. A later snapshot supersedes that account's previously effective positions without multiplying quantities.
- Detect exact duplicate uploads through file hash + source/account/snapshot identity. Keep import history and row-level provenance.
- Offer explicit replace/snapshot versus transactions semantics; never infer trades from two snapshot differences.

**Accept when:** Reimporting the same CSV leaves account holdings unchanged. An upload that replaces 10 shares with 12 results in 12, not 22. Unmatched tickers stay in review.

Stage 1 imports target one account/date; mixed files and duplicate security lines require correction. Unmatched/ambiguous position rows block commit, while unresolved fund constituents may remain residual after review. A fresh install must support reviewed local catalog creation without synthetic seeding. The [reviewed execution plan](stage-1-implementation-plan.md#review-decisions-and-implementation-handoff) defines correction/cancellation, captured revisions and duplicate uploads after a newer selected snapshot.

### P3 — Retrieve full ETF holdings and track freshness [MUST]

- Begin with 2–3 supported ETF formats, one parser each, and a user-uploaded issuer-CSV fallback.
- Persist **immutable, dated** issuer portfolio snapshots; show source link, effective date, fetch date, and recognized/unknown exposure percentage.
- Keep share classes as distinct securities; provide a separate optional issuer-level rollup (e.g., GOOG + GOOGL → Alphabet).
- Support stocks, nested ETFs, cash, and an `other/unclassified` bucket. Do not discard derivatives, shorts, or anomalous weights: flag unsupported funds.
- Fetch according to source-appropriate cadences and rate limits; avoid promising current intraday ETF composition.

**Accept when:** The same ETF at two reporting dates retains both versions; the UI shows which was used and whether it is stale or incomplete.

### P4 — Consolidated exposure dashboard [MUST; main value]

- Show `Owned positions` and `Look-through exposure` as separate tabs or clearly labeled views.
- Show company/security exposure in currency and share of **total included portfolio NAV** (including included cash, which has no company exposure).
- For an issuer, show direct contribution and one row for each contributing fund/account, with underlying snapshot date and quote date.
- Allow per-security and per-issuer views, account filtering, ETF expansion and export to CSV.
- Include unknown/other exposure explicitly. Show a coverage metric (proportion of portfolio value successfully attributed) and freshness badges.
- Prevent double counting: decomposing an ETF **replaces** its value in the look-through composition, but does not add value to owned positions or net worth.

**Worked example:** Own $30,000 of NVDA; ETF A position worth $50,000 with 8% NVDA; ETF B worth $20,000 with 6% NVDA; $100,000 other. NVIDIA exposure = $30,000 + $4,000 + $1,200 = **$35,200**, or **17.6%** of the $200,000 portfolio. If the user elects issuer rollups, combine an issuer's share classes only *after* calculating exposure at security level.

**Accept when:** This fixture produces exactly $35,200/17.6%; drill-down matches the sum; direct position totals and overall NAV remain $200,000.

### P5 — Reliability and understandability [MUST]

- Filter by account, ticker, issuer, and holdings source; label calculations as direct versus derived.
- Dates are displayed in a consistent format with timezone; monetary totals use base currency with FX conversion explicitly marked when applicable. For MVP, **USD-only import/valuation is acceptable**, while non-USD data must remain intact, flagged and excluded from converted totals until supported.
- Explain unavailable quote/holdings data rather than silently filling it in. Display calculation methodology for exposure percentages.

**Accept when:** Missing prices and missing/partial ETF holdings produce an incomplete-data banner and nonfabricated numbers, not a misleading 100%-coverage report.

Incomplete USD valuation reports the included valued subtotal and exclusions; total-portfolio percentages remain unavailable. Attribution coverage and valuation completeness are distinct. Report pagination, drill-down and export retain one frozen calculation identity across data changes/restarts. Search/top-N filter visible rows without changing account-selected NAV. Signed/unsupported allocation policies and exact residual reconciliation are specified in the [Stage 1 plan](stage-1-implementation-plan.md#deterministic-selection-and-financial-policy).

## 4. Stage 2 — Automated ingestion and personal finance

### Ingestion

- Local import of issuer statements and brokerage PDFs, screenshots, account-export webpages where permitted, CSV and image files.
- Finance-owned deterministic rule/template extraction first; generic OCR/structured interpretation through `PersonalAIClient` when an upstream contract is available. Validate and review candidates in finance before finalization; keep manual correction available without the AI service.
- Show extracted field, original evidence (page/table/line or image region when feasible), confidence/review status, and reconciliation differences.
- Preserve raw documents and original parsed payload; detect duplicates. No browser extension or credential-based account scraping in initial release.
- Optional Plaid read-only connection behind an adapter after eligibility, coverage, consent, privacy and pricing checks.

### Spending

- Import bank/credit-card transactions; categorize merchants and expense type; manually create/edit/correct transactions.
- Rules for recurring merchants, split transactions, refunds, account transfers and credit-card payments (not double-counted as expenses).
- Monthly spending and income trends, category drill-down, recurring charges, account balances, net worth.
- Transactions and balances have their own effective dates and sources; avoid silently treating missing months as zero spending.

**Acceptance:** Import a synthetic credit-card statement twice without duplicate transactions; classify a transfer between owned accounts as a transfer, not income + expense.

## 5. Stage 3 — Advanced investment intelligence

- Historical owned-position snapshots, cash movements, dividends and corporate actions; separate price return from contributions and withdrawals.
- Transaction-aware reconciliation and clearly scoped performance methodologies (time-weighted and money-weighted when sufficient data exists).
- Tax-lot model: source, purchase datetime, quantity remaining, basis, adjustments and verification status. Do not fabricate acquisition information from current holding data.
- Hypothetical sale planner with user-selected lots, high-basis / low-basis comparison, long/short-term classification, estimated realized gain or loss, fees and configurable **illustrative** tax rates.
- Warnings for potential wash sales across imported accounts; never certify tax compliance without full information.
- ETF overlap, allocation drift, thematic classifications (marked subjective/customizable), and hypothetical buy/sell scenarios with cash and exposure effects.
- Cash-flow planning, investment liquidity and large-purchase scenarios.

**Acceptance:** A simulated sale changes hypothetical cash, basis and remaining holdings, but does **not** modify real portfolio positions or send a trade.

## 6. Stage 5 — AI research and exploration

- Company profile with SEC filings, financial metrics, sourced summaries and links to original documents.
- Portfolio-aware research: holdings and exposure contextualize company news; maintain an investment-thesis journal.
- User-invoked research with cited excerpts and visible retrieval dates; optional monitored reports/alerts later.
- Generic search, evidence retrieval and synthesis through `PersonalAIClient` to `personal-ai-system`. Finance retains source references, dated results, citation checks, thesis/workflow records and deterministic metric validation; it does not build its own model routing, memory or research index. Neon remains the finance store without vector/full-text extension dependencies.
- AI outputs are explicitly research aids, not authoritative data sources, estimates of tax liability, or execution instructions.

## 7. Explicit non-goals and deferred functionality

- Trading/execution, brokerage password scraping, public financial-advice service, tax preparation/filing.
- Guaranteed real-time quotes or true real-time ETF transparency.
- Perfect tax-lot reconstruction from aggregate basis or position statements.
- Full derivatives/leverage/fund-of-funds decomposition in initial MVP; unsupported instruments remain visible in residual exposure.
- Multiuser SaaS, household permissions, mobile-native app, perpetual always-on cloud inference and paid institutional data feeds.

## 8. Product quality and accessibility

- Large, sortable/filterable financial tables; explain percentages and timestamps near values.
- Keyboard-friendly import review, readable layouts, no color-only gain/loss status.
- Export holdings and calculated exposure to CSV with source dates, methodology and unclassified rows.
- On failure, retain imported raw material and provide an actionable reason rather than corrupting canonical holdings.
- Synthetic sample portfolio and sample documents enable an entirely offline demonstration.

## 9. Open product choices (do not block Stage 0)

1. Initial set of ETF tickers and issuer formats; choose by the user's actual needs when starting Stage 1.
2. Account connection preference and whether personal data should ever leave the device.
3. At what threshold an ETF holdings snapshot is labeled stale (configurable per provider, not universal).
4. Whether non-USD conversion is needed before or after the first usable dashboard.
5. Whether the long-term product should remain single-user or support a household.


Provider-specific dated delivery facts are preserved in [the pre-migration snapshot](history/pre-gcp-neon/01-product-spec.md). [ADR 0002](adr/0002-gcp-neon.md) and the [migration record](gcp-neon-migration.md) define the current architecture; this plan does not claim additional product completion.
