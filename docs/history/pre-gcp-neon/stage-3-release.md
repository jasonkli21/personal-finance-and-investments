> Historical snapshot at `4e5f3e3`, preserved 2026-10-03. Deployment guidance is superseded by [ADR 0002](../../adr/0002-gcp-neon.md). Do not use this snapshot as current instructions.

# Stage 3 implementation status

**Status:** S3.1–S3.5 and S3.R complete locally; live Aurora DSQL production gate remains
**Updated:** 2026-10-02

Stage 3 implementation and local evaluation meet the [implementation plan](stage-3-implementation-plan.md). These notes record implemented behavior and verification. Production promotion remains blocked until the live Aurora DSQL gate described below passes.

## 2026-10-03 review update

The [repository review](maintainability-review.md) adds real PostgreSQL route workflows for deposit-neutral history/performance, lot publication/adjustment idempotency, read-only sale comparisons and liquidity planning. Those fixtures explicitly use a non-UTC database session to prevent effective-date regressions. The review fixes ordered scenario cash settlement, malformed tax CSV handling, field-specific review diagnostics, finite metadata and Decimal precision/serialization. Tax draft refetch/publication browser regressions pass, and the aggregate lint/format/type/test/build gate is now green. Historical checks below describe their original runs; the linked review records current counts and the remaining dated-lot evidence and DSQL limitations.

## S3.1 — Historical evidence and performance

Implemented explicit source-backed investment events, dated history reads, snapshot-to-event quantity reconciliation, and account-scoped performance reads. The API exposes event entry, history, reconciliation, and performance; the web UI shows snapshot/event history, comparison results, and diagnostics. Accepted position revisions remain the valuation source. Snapshot differences are reported as discrepancies; the application does not turn them into purchases, sales, contributions, or gains.

Event quantity deltas are signed from the account's perspective: purchases and transfers in are positive, sales and transfers out are negative. External cash flows use the portfolio perspective: contributions are positive and withdrawals are negative. Deposits and withdrawals are the only consolidated external performance flows. Per-account returns also neutralize transfers when a signed USD transfer value is supplied, or a USD cash-security quantity delta directly supplies that value; missing transfer valuation makes returns unavailable. Unsupported `other` events and unreviewed events also make returns unavailable. Dividends, fees, buys, and sells remain internal. Repeating an identical event with the same idempotency key returns the existing row; reusing the key for different content, including a changed quality status, conflicts.

### Implemented calculation policy

- Performance is per account and USD only. It is unavailable unless complete, non-stale, non-estimated accepted valuations exist on both requested boundary dates and on every selected observation date between them.
- The time-weighted view chains Modified Dietz subperiod estimates across observed snapshot dates. A flow effective on an interval's end date is treated as an end-of-day flow with zero weight; a flow on the opening date is already represented by the opening valuation. This is an estimate, not exact daily TWR.
- Money-weighted return uses annualized XIRR from the opening value, dated external flows, and ending value. A cash-flow series with multiple sign changes, no bracketed root, or insufficient valuations is reported unavailable/ambiguous rather than guessed. The bounded solver searches annual rates from -99.99% to 1,000% using Decimal bisection and a 365-day year.
- Both returned rates are fractions, serialized as decimal strings, rounded half-up to 12 places. The UI converts them to percent for display.
- Quantity reconciliation requires exact boundary snapshots and applies only explicit reviewed security quantity deltas. It skips unreviewed event effects and reports them as gaps. Reviewed buy, sell, dividend, and fee cash amounts are applied only when exactly one actual cash security for that currency is present in the opening snapshot; missing or ambiguous cash lines are reported as coverage gaps. Unsupported events remain gaps, and the calculation never publishes a balancing event.

### Verification

The Stage 3 event/performance API and pure calculation tests use synthetic records. The local DSQL migration-plan test validates the new table and async-index steps, and gated PostgreSQL/DSQL round-trip coverage was added. Local checks run for this package:

- `uv run --directory services/api --locked pytest -q tests/test_stage3_performance.py tests/test_stage3_history.py tests/test_dsql_migrations.py` — 15 passed.
- Ruff checks, focused mypy, and the web TypeScript typecheck passed.
- The S3.1 API behavior is covered by synthetic SQLite tests. The Stage 3 migration chain was later exercised successfully on PostgreSQL 16.15 as part of S3.R, but dedicated PostgreSQL route coverage for the history/performance endpoints was not added. The credentialed DSQL integration suite was not run; live DSQL remains unverified.

## S3.2 — Source-backed tax lots

Added migrations `0013_stage3_tax_lots` and `0014_stage3_tax_lot_fences` for private import reviews, raw import rows, published lots, append-only lot adjustments, import audit events, and a shared optimistic lot-state revision. The matching DSQL plan uses one DDL statement per transaction and asynchronous indexes. Lot quantities and basis use `NUMERIC(28, 10)`; acquisition date, initial quantity, basis values, currency, and evidence references remain nullable when absent in the source.

The API accepts a mapped UTF-8 CSV with at most 500 rows and the configured private-file byte limit. The original bytes stay in owner-only local storage; the database keeps the content hash and raw row payload. Exact ticker matches resolve only to catalog equity and ETF securities. Unknown/ambiguous tickers, unsupported security types, malformed required quantities, future acquisition dates, and basis values without a currency remain in review. Missing acquisition date or basis stays unavailable. Duplicate file/source/account imports return the earlier review; repeated source lot identities are skipped instead of overwriting accepted evidence.

Review compares account lot quantities, including published lots and append-only quantity adjustments, with the selected accepted position snapshot. It reports missing snapshot coverage and per-security differences; it never changes a position or invents a lot. Publication is limited to 500 staged rows and the `TAX_LOT_PUBLICATION_MAX_ROWS` setting can lower that bound; oversized imports fail before any publication write. Publication and row correction use a conditional shared review-revision/status update, repeated publication is idempotent, and duplicate source identities that appeared after review are skipped as duplicates. Row corrections and publication are retained as immutable audit events with reasons. Adjustment requests require source, effective date, reason and an idempotency key; basis adjustments require known remaining basis and currency. A conditional lot-state revision serializes append-only adjustment validation, and chronological effective states must remain nonnegative. Imported values and source payload remain available after corrections.

The web workspace maps CSV columns, reviews original rows and diagnostics, lets the user resolve security matches and correct row fields, displays quantity reconciliation, gates publication, and shows the published lot basis/date quality. It also records source-backed quantity/basis adjustments while keeping imported values immutable.

The local focused checks are:

```sh
UV_CACHE_DIR=/private/tmp/codex-personal-finance-uv-cache uv run --directory services/api --locked pytest -q tests/test_stage3_tax_lots.py tests/test_stage3_history.py tests/test_stage3_performance.py tests/test_dsql_migrations.py tests/test_database_engine.py
```

The focused API/migration/dialect suite passes (22 tests). S3.R ran the full API suite on a temporary PostgreSQL 16.15 cluster; see its results below. The initial S3.2 checks did not exercise the PostgreSQL migration. S3.R found that the raw-row and published-lot tables declared the same PostgreSQL unique-index name. The migration had not been successfully applied; it now uses the distinct `uq_tax_lots_import_row` name in the migration, ORM metadata and DSQL plan. The fresh migration and schema round trip pass on PostgreSQL 16.15. The reviewed lot import API tests remain synthetic SQLite tests, and the credentialed DSQL integration suite was not run. The full `pnpm check` stops at existing React state-in-effect lint findings in `FinanceWorkspace.tsx`, `SpendingWorkspace.tsx`, and `StageOneWorkspace.tsx`; full repository Ruff formatting also reports the already-applied `0007_stage2_document_ingestion.py`, which remains unchanged. Production promotion remains blocked on live DSQL evidence.

## S3.3 — Hypothetical lot-sale comparison and qualified warnings

Added the read-only `POST /v1/simulations/sales` API and a two-selection comparison in the tax-lot workspace. A request names one actual account/security, a sale date, a share or gross-value target, fees for each comparison, and explicit per-lot quantities for one or two scenarios. The selected quantities must equal the requested share target. Value targets convert to shares by rounding down at 10 decimal places; the returned remainder shows the value not represented by those shares.

The simulation freezes the account position revision, accepted snapshot and position line, source-backed price ID/as-of/source/quality, selected published lot states, and effective adjustments through the sale date into fingerprints. A price more than seven days before the accepted snapshot, an accepted snapshot more than seven days old, estimated/stale quality, unsupported security, nonpositive quantity/price, date before the snapshot, or over-sale is rejected. The current reported price remains a disclosed constant assumption through a future sale date. Per-lot basis is allocated proportional to selected shares, rounded half-up to 10 decimal places; selling a lot in full uses its exact remaining basis. Fees reduce net proceeds and estimated gain. Missing or mismatched basis/currency makes total gain unavailable. No scenario rows or canonical finance records are written.

Holding-period labels use policy `us-federal-pub550-2025-holding-period-wash-sale-v1` and are ordinary U.S. federal candidates based on the recorded acquisition date. Missing dates and leap-day anniversaries remain unknown. Exceptions and prior-period tacking are not modeled. A possible wash-sale warning scans reviewed positive buy events and recorded tax-lot acquisition dates with the exact same local security ID from 30 days before through 30 days after the hypothetical sale date. It never equates different IDs by ticker, never computes a disallowed-loss amount, and always reports coverage as unknown. No match is not compliance clearance. Source verification and limits are documented in [the data-source policy](03-data-sources.md) and linked from the UI to [IRS Publication 550](https://www.irs.gov/publications/p550). The [IRS 2026 Form 1099-B instructions](https://www.irs.gov/instructions/i1099b) are also listed there to distinguish a broker reporting rule from complete household coverage.

The workspace shows both per-scenario summaries and per-lot proceeds, basis, estimated gain/loss, remaining hypothetical quantities/basis, price provenance, baseline fingerprint, and warning evidence. It marks the displayed result stale if the current account position revision, selected lot values, or simulation inputs have changed and offers a refresh. Results remain tied to the original calculation fingerprint.

Focused verification after S3.3:

```sh
UV_CACHE_DIR=/private/tmp/codex-personal-finance-uv-cache uv run --directory services/api --locked pytest -q tests/test_stage3_sales.py tests/test_stage3_tax_lots.py tests/test_stage3_history.py tests/test_stage3_performance.py tests/test_dsql_migrations.py tests/test_database_engine.py
```

This command passed 29 tests. It includes the two-lot $500/$200 golden comparison, proportional partial-lot basis/fees/value rounding, unavailable basis, a cross-account potential warning, stale-price/snapshot and over-sale rejection, and unchanged canonical record counts/revisions across simulation. Focused Ruff, mypy, web TypeScript, changed-file ESLint, production build and generated OpenAPI checks passed. Full API and web-suite results are recorded in the final Stage 3 review. The sale simulator adds no persistent schema and therefore no PostgreSQL/DSQL migration. The route has not been exercised against a live PostgreSQL 16 instance or Aurora DSQL; those production-gate checks remain outstanding.

## S3.4 — Hypothetical portfolio scenarios

Added read-only `POST /v1/simulations/portfolio` and a portfolio scenario workspace. A request freezes the accepted position revisions and dated exposure inputs, then applies up to 100 explicit USD equity/ETF trades plus signed, labeled USD cash assumptions. Account selection, date, share quantity, trade price and fees are explicit; only cash-only financing is supported. A buy must be funded by available USD cash, and a sale cannot exceed an actually owned position. Foreign-currency trades and cash assumptions are rejected. Existing holdings retain the frozen baseline valuation price; a new position uses the entered trade price until a source-backed valuation exists. If an existing position's execution price differs from its baseline valuation price, the difference changes modeled NAV and is disclosed.

Before and after calculations use the existing versioned one-level exposure engine with the latest published fund composition dated on or before the valuation date. An ETF absent from the baseline is loaded from the same dated local evidence when available; missing composition remains opaque. The API returns included valued NAV, completeness, direct assets, indirect look-through, residual categories, security/issuer exposure, per-fund overlap membership and shared dollar exposure, custom category drift, cash settlement, data warnings, methodology versions, and fingerprints. Direct + indirect + residual must reconcile to valued NAV on each side. Look-through and overlap are decomposition/analysis only and do not increase owned value. Foreign-currency, unpriced and unresolved baseline positions make NAV incomplete and receive explicit warnings; custom actual percentages are withheld for incomplete valuations.

The UI compares baseline and scenario allocations, top security/issuer rows, cash and trade fees, overlap, fund evidence, warnings, and fingerprints. It flags current account revisions that have changed since a same-day result, keeps historical results frozen, and allows a JSON export. Results are never saved by the application and no canonical finance rows are changed.

Focused S3.4 verification:

```sh
UV_CACHE_DIR=/private/tmp/codex-personal-finance-uv-cache uv run --directory services/api --locked pytest -q tests/test_stage3_performance.py tests/test_stage3_portfolio_scenarios.py tests/test_stage3_sales.py tests/test_stage3_tax_lots.py tests/test_stage3_history.py
```

This command passed 23 tests. Scenario cases cover fee/cash reconciliation, category drift, an ETF buy using dated look-through, an ETF sale that removes indirect exposure and adds proceeds to cash, shared-membership overlap without NAV double counting, an opaque fund with foreign cash/no FX conversion, insufficient cash, overselling, explicit cash assumptions, rejected foreign-currency trades, and unchanged accepted position records/revisions. Focused Ruff and mypy passed; web tests (9), TypeScript, changed-file ESLint, production build, and regenerated OpenAPI checks passed. The scenario route adds no schema or migration and has not been exercised against live PostgreSQL 16 or Aurora DSQL. Both live database gates remain outstanding.

## S3.5 — Income, runway, and purchase planning

Added the read-only `POST /v1/planning/scenarios` API and planning workspace. A request selects active accounts and an as-of date, a 1–120 month projection horizon, and a 1–60 month completed-calendar-month history window. It requires explicit monthly USD income, expense and dividend assumptions with source labels. History is displayed as evidence and context only; it never fills or generates the projection. Transactions are grouped by source currency, transfers/card payments are excluded, unclassified rows and missing coverage remain visible, and reviewed dividend events remain separate from transaction income because the two may overlap.

The baseline selects the latest eligible dated account balance or position snapshot per account. It groups known values by currency into liquid cash, investments, restricted assets, other assets and liabilities without FX conversion. Retirement-account positions remain restricted; liabilities are signed separately and are not automatically paid. A position snapshot's balance observation is excluded to avoid double counting. Position snapshot and valuation-price dates, sources, quality, and revisions are returned separately. Missing cash lines, stale/estimated/unpriced values, overlapping balance observations and missing account evidence produce explicit completeness warnings. An optional starting-cash override replaces observed USD cash only for the projection and is marked as a user assumption; it does not change the balance sheet.

The monthly cash projection uses Decimal arithmetic and three bounded sensitivity cases. Recurring signed changes and dated one-time purchases, liability payments or other changes apply in their selected months. A purchase is a cash outflow only; the scenario does not liquidate assets, borrow, model taxes or change account balances. The UI reports base-case month-by-month cash, ending cash and first nonpositive month, historical cash-flow context, assumptions/source labels, warnings, input revisions and a deterministic fingerprint. Results are not saved; JSON export is client-side.

Focused S3.5 verification:

```sh
UV_CACHE_DIR=/private/tmp/codex-personal-finance-uv-cache uv run --directory services/api --locked pytest -q tests/test_stage3_performance.py tests/test_stage3_planning.py tests/test_stage3_portfolio_scenarios.py tests/test_stage3_sales.py tests/test_stage3_tax_lots.py tests/test_stage3_history.py
```

This command passed 27 tests, including explicit income/expense/dividend assumptions, a scheduled purchase, sensitivity calculations, retirement and unknown-cash handling, liability separation, missing history, validation bounds, and unchanged canonical record counts. Focused Ruff, formatting, mypy, web TypeScript, changed-file ESLint, web tests (9), production build, and generated OpenAPI validation passed. The planning endpoint adds no persistent schema or migration. It was exercised with synthetic SQLite fixtures only; live PostgreSQL 16 and Aurora DSQL runtime checks remain outstanding.

## S3.R — Final evaluation and release gate

The local Stage 3 acceptance review is complete:

| Review area | Evidence and result |
| --- | --- |
| Historical evidence and returns | Events retain source and review status. Deposits do not become market return; Modified Dietz is labeled an estimate, and ambiguous or insufficient XIRR inputs remain unavailable. |
| Supplied tax lots | Raw rows and unknown fields remain reviewable. A synthetic two-lot sale produces the golden $500 versus $200 estimated gains before fees, with no canonical lot or position mutation. |
| Tax warnings | Holding-period candidates and potential same-security wash-sale activity use a versioned, cited U.S. federal policy; unknown coverage is never presented as clearance. |
| Portfolio scenarios | Before/after direct assets, look-through and residual reconcile to valued NAV in synthetic cases. Overlap and indirect exposure do not add to net worth. |
| Liquidity planning | Income, expense and dividend inputs require explicit values and source labels. Cash, investments, restricted assets and liabilities remain separated; purchases reduce only projected cash. Missing coverage and non-USD balances stay visible. |
| Database gate | Full API tests pass on PostgreSQL 16.15. Aurora DSQL remains unverified; production promotion is blocked on the credentialed DSQL migration and runtime suite. |

The final full API run on a temporary PostgreSQL 16.15 cluster passed **134 tests with 9 skipped**. It covered the fresh Alembic chain through Stage 3 migrations, populated-schema upgrade, repository behavior, and transaction/concurrency tests. The 9 skips are the opt-in DSQL integration cases; no disposable Aurora DSQL cluster was available. The separate PostgreSQL integration group passed 39 tests with 2 skipped. Stage 3 endpoint behavior, including reviewed lot import, history/performance, sale/portfolio simulation and planning, continues to use synthetic SQLite fixtures rather than a dedicated PostgreSQL endpoint suite.

Local frontend and contract checks passed: 9 web tests, TypeScript, changed-file ESLint, Prettier, generated OpenAPI validation and the production build. Full repository Ruff checks and mypy passed. The production build succeeds; Vite warns that the main JavaScript bundle exceeds 500 kB after minification.

The aggregate `pnpm check` command stops at repository-wide web lint because of four existing `react-hooks/set-state-in-effect` findings in `FinanceWorkspace.tsx`, `SpendingWorkspace.tsx` and `StageOneWorkspace.tsx`; changed Stage 3 files pass ESLint. The full Python `ruff format --check .` reports the already-applied `0007_stage2_document_ingestion.py`; it was left unchanged under the migration immutability rule. The changed Stage 3 Python files pass formatting checks. These repository-wide checks do not alter the passing test, type, migration or generated-contract results.

The PostgreSQL run caught and corrected a Stage 3.2 schema defect: `tax_lot_import_rows` and `tax_lots` had declared the same unique-index name. The distinct `uq_tax_lots_import_row` name is now consistent across ORM metadata, Alembic and the DSQL plan, and a regression test rejects duplicate named unique constraints across tables. Fresh PostgreSQL 16.15 migration and schema round-trip now pass. No live DSQL claim is made from that result or from the structural DSQL plan tests.

**Release decision:** Stage 3 is complete for local development. Do not promote to production until the real Aurora DSQL migration, synthetic persistence, retry and runtime checks pass on a disposable cluster, and any resulting DSQL issues are resolved.

## Follow-up correctness fixes — 2026-10-02

The Stage 3 review follow-up closes return and reconciliation coverage gaps, adds the `0014_stage3_tax_lot_fences` optimistic lot-state revision, and makes tax review correction/publication conditional on the shared review revision and status. Adjustment publication validates each chronological effective state; publication repeats are idempotent, duplicate identities discovered after review are skipped, and `TAX_LOT_PUBLICATION_MAX_ROWS` can lower the 500-row hard limit. Scenario arithmetic now runs above `NUMERIC(28, 10)` input precision, checks output bounds, and converts decimal overflow to a domain validation response. Planning baseline totals and tax-lot aggregation use the same high-precision context.

Synthetic regression coverage now includes transfer-neutral account returns and unavailable transfer values, unsupported/unreviewed events, cash-linked buy/fee reconciliation, quality-sensitive event idempotency, same-day MWR flows, stale tax revisions, repeat/duplicate lot publication, chronological adjustment rejection, configured publication bounds, and large fractional scenario reconciliation. The full offline API suite passes 124 tests with 30 opt-in tests skipped; focused Ruff, formatting, mypy, generated API validation and web TypeScript checks pass. PostgreSQL was unavailable during this follow-up and the credentialed Aurora DSQL tests remain unrun, so migration/runtime behavior on those databases is not claimed.

Parent light-pass verification: a same-day adjustment timestamp comparison was corrected and covered by the chronology regression. On 2026-10-02, the complete API suite against a disposable PostgreSQL 16 cluster passed **145 tests, 9 skipped** (real DSQL remains unverified). This includes fresh and populated upgrade migrations through `0014_stage3_tax_lot_fences`; dedicated Stage 3 routes remain SQLite synthetic coverage.
