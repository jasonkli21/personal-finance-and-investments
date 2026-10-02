# Stage 3 implementation status

**Status:** In progress; S3.1 history/performance delivered locally  
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
