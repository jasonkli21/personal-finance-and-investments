# Stage 3 implementation status

**Status:** In progress; S3.1 and S3.2 delivered locally
**Updated:** 2026-10-02

Stage 3 remains incomplete until S3.1–S3.5 and S3.R meet the [implementation plan](stage-3-implementation-plan.md). These notes record implemented behavior and verification, not the remaining planned scope. Local PostgreSQL and live Aurora DSQL evidence are tracked separately.

## S3.1 — Historical evidence and performance

Implemented explicit source-backed investment events, dated history reads, snapshot-to-event quantity reconciliation, and account-scoped performance reads. The API exposes event entry, history, reconciliation, and performance; the web UI shows snapshot/event history, comparison results, and diagnostics. Accepted position revisions remain the valuation source. Snapshot differences are reported as discrepancies; the application does not turn them into purchases, sales, contributions, or gains.

Event quantity deltas are signed from the account's perspective: purchases and transfers in are positive, sales and transfers out are negative. External cash flows use the portfolio perspective: contributions are positive and withdrawals are negative. Deposits and withdrawals are the only event types treated as external performance flows; dividends, fees, buys, sells, and account transfers remain internal. Repeating an identical event with the same idempotency key returns the existing row; reusing the key for different content conflicts.

### Implemented calculation policy

- Performance is per account and USD only. It is unavailable unless complete, non-stale accepted valuations exist on both requested boundary dates and on every selected observation date between them.
- The time-weighted view chains Modified Dietz subperiod estimates across observed snapshot dates. A flow effective on an interval's end date is treated as an end-of-day flow with zero weight; a flow on the opening date is already represented by the opening valuation. This is an estimate, not exact daily TWR.
- Money-weighted return uses annualized XIRR from the opening value, dated external flows, and ending value. A cash-flow series with multiple sign changes, no bracketed root, or insufficient valuations is reported unavailable/ambiguous rather than guessed. The bounded solver searches annual rates from -99.99% to 1,000% using Decimal bisection and a 365-day year.
- Both returned rates are fractions, serialized as decimal strings, rounded half-up to 12 places. The UI converts them to percent for display.
- Quantity reconciliation requires exact boundary snapshots, applies only explicit reviewed security quantity deltas, reports per-security differences and unsupported event gaps, and never publishes a balancing event.

### Verification

The Stage 3 event/performance API and pure calculation tests use synthetic records. The local DSQL migration-plan test validates the new table and async-index steps, and gated PostgreSQL/DSQL round-trip coverage was added. Local checks run for this package:

- `uv run --directory services/api --locked pytest -q tests/test_stage3_performance.py tests/test_stage3_history.py tests/test_dsql_migrations.py` — 15 passed.
- Ruff checks, focused mypy, and the web TypeScript typecheck passed.
- PostgreSQL 16 migration/runtime tests were not run for this package. The credentialed DSQL integration suite was not run; live DSQL remains unverified.

## S3.2 — Source-backed tax lots

Added migration `0013_stage3_tax_lots` for private import reviews, raw import rows, published lots, append-only lot adjustments, and import audit events. The matching DSQL plan uses one DDL statement per transaction and asynchronous indexes. Lot quantities and basis use `NUMERIC(28, 10)`; acquisition date, initial quantity, basis values, currency, and evidence references remain nullable when absent in the source.

The API accepts a mapped UTF-8 CSV with at most 500 rows and the configured private-file byte limit. The original bytes stay in owner-only local storage; the database keeps the content hash and raw row payload. Exact ticker matches resolve only to catalog equity and ETF securities. Unknown/ambiguous tickers, unsupported security types, malformed required quantities, future acquisition dates, and basis values without a currency remain in review. Missing acquisition date or basis stays unavailable. Duplicate file/source/account imports return the earlier review; repeated source lot identities are skipped instead of overwriting accepted evidence.

Review compares account lot quantities, including published lots and append-only quantity adjustments, with the selected accepted position snapshot. It reports missing snapshot coverage and per-security differences; it never changes a position or invents a lot. Publication is limited to 500 staged rows in one short database transaction, uses a review revision check, and requires explicit acknowledgement for coverage gaps or quantity differences. Row corrections and publication are retained as immutable audit events with reasons. Adjustment requests require source, effective date, reason and an idempotency key; basis adjustments require known remaining basis and currency. Imported values and source payload remain available after corrections.

The web workspace maps CSV columns, reviews original rows and diagnostics, lets the user resolve security matches and correct row fields, displays quantity reconciliation, gates publication, and shows the published lot basis/date quality. It also records source-backed quantity/basis adjustments while keeping imported values immutable.

The local focused checks are:

```sh
UV_CACHE_DIR=/private/tmp/codex-personal-finance-uv-cache uv run --directory services/api --locked pytest -q tests/test_stage3_tax_lots.py tests/test_stage3_history.py tests/test_stage3_performance.py tests/test_dsql_migrations.py tests/test_database_engine.py
```

The focused API/migration/dialect suite passes (22 tests). The full local API suite passes 95 tests with 30 skipped; the skips include PostgreSQL and credentialed DSQL gates. Web tests (9), TypeScript, production build, Ruff, mypy, generated OpenAPI validation, and ESLint for changed web files pass. The full `pnpm check` is still blocked by existing React state-in-effect lint findings in `FinanceWorkspace.tsx`, `SpendingWorkspace.tsx`, and `StageOneWorkspace.tsx`; its repository-wide Ruff format check also reports the already-applied `0007_stage2_document_ingestion.py`. That migration was left unchanged per the migration immutability rule. A gated live-DSQL migration/round-trip case now covers a lot import row, fractional lot, and adjustment, but no credentialed Aurora DSQL cluster was available here. PostgreSQL 16 migration/runtime verification for these changes also remains unrun. Production promotion remains blocked on live DSQL evidence.
