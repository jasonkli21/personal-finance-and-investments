# Phase 30 Finance discretionary budget evidence

Date: 2026-10-11. Tested baseline: `bb53668` plus the local Phase 30 changes.

Finance now owns one monthly discretionary-budget record per period with a revisioned amount, uppercase currency, and explicit `share_with_shopping` consent that defaults off. The owner-facing API requires an expected revision for create/update and rejects malformed periods, stale revisions, invalid amounts, and invalid currency. Migration `0019_monthly_discretionary_budgets` is the local Alembic head.

The Finance context projection accepts only one selected budget and the exact `amount`, `currency`, and `period` fields for `shopping_discretionary_budget` to Shopping. Its verify operation rechecks current consent and source version. Revoking consent advances the source state and makes both read and verify unavailable. No accounts, holdings, transactions, balances, or broader financial data are included.

Checks on the working tree: `tests/test_finance_context.py tests/test_discretionary_budget.py` — **15 passed**; Ruff passed; Alembic head check reports `0019_monthly_discretionary_budgets`.

The Personal AI adapter remains behind the default-off Finance context gate. Shopping has no accepted user-bound typed task transport or sidecar host, and no deployed identity, migration, grant-selection, live-revocation, or browser checks were run. Finance → Shopping is not end-to-end available.

## 2026-10-13 stabilization verification

Tested revision: Finance `495c21186b68215bf110ab6ab3115cd67190cc67` plus the uncommitted working-tree changes. The canonical `pnpm api:generate` refreshed both checked-in artifacts with `GET`/`PUT /v1/finance/discretionary-budgets/{period}` and the `MonthlyDiscretionaryBudgetRead`/`MonthlyDiscretionaryBudgetWrite` schemas; `pnpm api:check` then passed. The generated output is owned by FastAPI routes/contracts and the exporter; the workflow is documented in [API contract ownership](02-architecture.md#api-contract-ownership).

The previously failing `test_cached_quote_asof_precedence_and_signed_percentages` had a stale expected total because its 2026-10-01 quote was more than the default seven-day freshness window old on the test date. The service correctly marked that valuation incomplete and returned `total_usd: null`. The test now freezes its read clock at 2026-10-02, when that quote is fresh, so it continues to test quote precedence and signed percentages. Production valuation behavior and expected financial values were not changed. The same check exposed stale type/schema assertions left at the pre-Phase-30 counts and Alembic head; those now reflect the current 46-table/36-index schema and `0019_monthly_discretionary_budgets`.

The repository-pinned pnpm 11.19.0 check ran with Node v24.19.0 and Python 3.12.13 and passed: API freshness, frontend/Ruff lint, formatting, TypeScript, mypy (117 source files), 8 frontend test files/22 tests, 6 infrastructure contract tests, and the API suite (**244 passed, 55 skipped**); the web production build completed with Vite's existing large-chunk advisory. The run had `TEST_DATABASE_URL`, Neon variables, and recovery admin URL unset. PostgreSQL-backed acceptance is therefore still open; `127.0.0.1:55439` did not respond to `pg_isready` during this check. `pnpm --filter web exec playwright test --list` discovered all 7 journeys in 2 files, but none were executed because PostgreSQL was unavailable. No GitHub CI run was triggered for the uncommitted worktree.

The targeted valuation test also passed independently. No cloud, provider, deployed-identity, live grant/revocation, PostgreSQL, or browser acceptance is claimed.
