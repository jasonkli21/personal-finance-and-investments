# Stage 1 delivery evidence

Status: S1.1 delivered; S1.2 delivered; S1.3 pending. This record is updated only with observed results.

- Planning: `60d2ed3`; prerequisite PostgreSQL ledger fix: `99f6a41`; S1.1 implementation: `f75e101`.
- S1.1 agent evidence: PostgreSQL 16.15 suite 55 passed, 3 live DSQL skipped; aggregate quality passed (8 Vitest, 53 pytest/5 skipped, generated contracts, lint, formatting, strict types and web build).
- Local disposable PG16 runtime: port 55432, database `portfolio_stage0_gate`; it contains synthetic test data only. Test URL: `postgresql+psycopg://postgres@127.0.0.1:55432/portfolio_stage0_gate`.
- Live DSQL remains unverified and production blocked. Applied migrations stay immutable; new versioned fund DDL/index steps are separate from PostgreSQL Alembic.
- Optional live quote integration is omitted. Manual/cached quotes remain available. Automatic issuer downloads are disabled pending verified rights; both official-download formats and manual CSV are supported through explicit review/accept.

S1.2 verification (2026-10-02): `pnpm check` passed (8 Vitest, 56 pytest passed/7 database skips, all quality/type/build checks); full PG16 suite passed 60/3 live DSQL skips. Two synthetic format parsers, 502-row three-batch publication, duplicate/history, correction/cancellation and opaque overweight tests passed on SQLite and actual PostgreSQL.

## Fund upload workflow

Create ETF and constituent securities locally, select ETF under **ETF compositions**, confirm effective date, select Generic CSV/iShares IVV CSV/SPDR SPY Excel, map the generic headers and weight unit, and preview. Correct invalid weights using decimal units or resolve identifiers. **Accept fund composition** explicitly acknowledges unresolved/raw anomalies; invalid weights block publication. Cancel leaves prior history intact. Every raw row is retained; accepted fund snapshots never create owned positions. History displays effective/source dates and quality/warnings. Generic CSV has `ticker,weight,type`; weight units are explicit. Synthetic golden compositions live in `fixtures/stage-1`.

Configured input limits: `MAX_IMPORT_FILE_BYTES` (default 5 MB), `MAX_IMPORT_ROWS` (default 5,000), private `PRIVATE_FILE_DIR`; review/publication batches max 200 rows and 900 KB raw payload. XLSX additionally caps entries (100), total uncompressed bytes (20 MB), rows, columns and disallows formula/DTD/entity XML content. No macro execution or public file endpoint exists.
