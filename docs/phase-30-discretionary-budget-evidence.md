# Phase 30 Finance discretionary budget evidence

Date: 2026-10-11. Tested baseline: `bb53668` plus the local Phase 30 changes.

Finance now owns one monthly discretionary-budget record per period with a revisioned amount, uppercase currency, and explicit `share_with_shopping` consent that defaults off. The owner-facing API requires an expected revision for create/update and rejects malformed periods, stale revisions, invalid amounts, and invalid currency. Migration `0019_monthly_discretionary_budgets` is the local Alembic head.

The Finance context projection accepts only one selected budget and the exact `amount`, `currency`, and `period` fields for `shopping_discretionary_budget` to Shopping. Its verify operation rechecks current consent and source version. Revoking consent advances the source state and makes both read and verify unavailable. No accounts, holdings, transactions, balances, or broader financial data are included.

Checks on the working tree: `tests/test_finance_context.py tests/test_discretionary_budget.py` — **15 passed**; Ruff passed; Alembic head check reports `0019_monthly_discretionary_budgets`.

The Personal AI adapter remains behind the default-off Finance context gate. Shopping has no accepted user-bound typed task transport or sidecar host, and no deployed identity, migration, grant-selection, live-revocation, or browser checks were run. Finance → Shopping is not end-to-end available.
