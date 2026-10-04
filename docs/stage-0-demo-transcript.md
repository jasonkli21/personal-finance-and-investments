> Dated historical evaluation. Provider assumptions are superseded by [ADR 0002](adr/0002-gcp-neon.md); current validation is in [the migration record](gcp-neon-migration.md).

# Stage 0 synthetic demo transcript

**Run date:** 2026-10-02

**Purpose:** Browser smoke of create → manual entry → reload using only synthetic data.

## Browser/API walkthrough

The API was started against a disposable SQLite file in `/private/tmp` with the
same SQLAlchemy metadata and `seed_demo_data` function. Vite used its local
`/api` proxy. No provider calls, credentials, or real account data were used.
This verifies the browser/API interaction; it is not PostgreSQL 16 or DSQL
evidence.

1. The app loaded with `API and database: ready` and listed the two seeded
   `[SYNTHETIC]` accounts. The selection list showed `SYNTHETIC DEMO` and the
   selected demo account displayed `Synthetic demo account · fictional data
   only`.
2. Created `[SYNTHETIC] Browser smoke` as a taxable USD account.
3. Added `SYN1`, quantity `1.25`, manual price `120.50`, and saved revision 1
   dated `2026-10-02`. The persisted value displayed as USD `150.6250000000`.
4. Reloaded the browser, selected `[SYNTHETIC] Browser smoke` again, and
   confirmed the API returned revision 1 with the same quantity, price, date,
   and value.
5. Selected `[SYNTHETIC] Taxable example` and confirmed its persisted snapshot
   showed SYN1 USD 360, SYNX USD 200, and an explicit USD cash balance of 100,
   each dated 2026-09-30 with `synthetic_demo` source and `synthetic` quality.

## Seed verification

`seed_demo_data` ran against the same disposable SQLite schema. The first run
created 3 issuers, 3 aliases, 5 securities, 4 dated quotes, 2 accounts, 2
snapshots, and 6 position lines. The second run created zero rows. Pytest also
checked Decimal expected values of USD 660 taxable, USD 520 Roth IRA, and USD
1,180 combined; confirmed explicit cash; preserved a user edit on reseed; and
verified reset preserves unrelated rows and refuses a demo security referenced
from a non-demo account.

## Current verification boundary

`pnpm check` passed on 2026-10-02: 7 Vitest tests, 37 pytest tests, and a
successful production web build. Three database-gated tests were skipped: one
requires a disposable PostgreSQL 16 database and two require a disposable
Aurora DSQL cluster. The browser/API smoke used SQLite and does not substitute
for either. No PostgreSQL runtime migration was run in this verification pass;
the prior offline Alembic SQL generation is recorded above in the S0.5 evidence.
