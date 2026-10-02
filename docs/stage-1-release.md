# Stage 1 delivery evidence

Status: Stage 1 local MVP delivered (S1.1, S1.2, S1.3). Live DSQL and production launch remain unverified. This record is updated only with observed results.

- Planning: `60d2ed3`; prerequisite PostgreSQL ledger fix: `99f6a41`; S1.1 implementation: `f75e101`; S1.2 implementation: `9053d1f`. S1.3 is the commit containing this release record.
- S1.1 agent evidence: PostgreSQL 16.15 suite 55 passed, 3 live DSQL skipped; aggregate quality passed (8 Vitest, 53 pytest/5 skipped, generated contracts, lint, formatting, strict types and web build).
- Local disposable PG16 runtime: port 55432, database `portfolio_stage0_gate`; it contains synthetic test data only. Test URL: `postgresql+psycopg://postgres@127.0.0.1:55432/portfolio_stage0_gate`.
- Live DSQL remains unverified and production blocked. Applied migrations stay immutable; new versioned fund DDL/index steps are separate from PostgreSQL Alembic.
- Optional live quote integration is omitted. Manual/cached quotes remain available. Automatic issuer downloads are disabled pending verified rights; both official-download formats and manual CSV are supported through explicit review/accept.

S1.2 verification (2026-10-02): `pnpm check` passed (8 Vitest, 56 pytest passed/7 database skips, all quality/type/build checks); full PG16 suite passed 60/3 live DSQL skips. Two synthetic format parsers, 502-row three-batch publication, duplicate/history, correction/cancellation and opaque overweight tests passed on SQLite and actual PostgreSQL.

S1.3 final verification (2026-10-02): aggregate `pnpm check` passed (9 Vitest tests; 61 API tests passed/18 environment skips; generated OpenAPI/TypeScript freshness, lint, formatting, strict types and production web build). The full actual PostgreSQL 16.15 suite passed **71 tests / 8 skipped**: seven credentialed DSQL tests and the SQLite-only concurrency exclusion. The PostgreSQL concurrent-publication variant passed. Offline Chromium Playwright journey passed **1/1**, using the disposable PG16 browser database and actual migrations. A Starlette/httpx deprecation warning remains; no failed checks remain. Remote CI and live DSQL execution are not claimed.

## Fund upload workflow

Create ETF and constituent securities locally, select ETF under **ETF compositions**, confirm effective date, select Generic CSV/iShares IVV CSV/SPDR SPY Excel, map the generic headers and weight unit, and preview. Correct invalid weights using decimal units or resolve identifiers. **Accept fund composition** explicitly acknowledges unresolved/raw anomalies; invalid weights block publication. Cancel leaves prior history intact. Every raw row is retained; accepted fund snapshots never create owned positions. History displays effective/source dates and quality/warnings. Generic CSV has `ticker,weight,type`; weight units are explicit. Synthetic golden compositions live in `fixtures/stage-1`.

Configured input limits: `MAX_IMPORT_FILE_BYTES` (default 5 MB), `MAX_IMPORT_ROWS` (default 5,000), private `PRIVATE_FILE_DIR`; review/publication batches max 200 rows and 900 KB raw payload. XLSX additionally caps entries (100), total uncompressed bytes (20 MB), rows, columns and disallows formula/DTD/entity XML content. No macro execution or public file endpoint exists.

## Reconciled exposure and frozen report workflow

Create accounts and securities in the local catalog, then enter manual positions or map/review a position CSV. Set the position date and confirm the chosen account. Accept a dated fund composition separately. Under **Portfolio reports**, select included accounts (none means all active), optionally set a historical valuation timestamp, and create a report. Default selection uses account published pointers; historical selection uses the latest effective published history not later than the requested timestamp. Future observations and unpublished staging are excluded. The editor's **Snapshot-date owned value** is a historical inspection using the position date; use Portfolio reports for current valuation and authoritative exposure.

The dashboard has separate owned, security look-through, and issuer views. Reviewed share-class mappings alone enable issuer rollups. Search/source filters and value/name sorting apply to paginated rows (50 per page), preserving the account-selected NAV. Select a security/issuer or decomposition category for account/fund contributions, weights, source dates, statuses and source links. Residuals remain visible even when row filters hide securities. Export uses the same report identity and selected row filters, with full portfolio residual categories labelled separately. Issuer-unmapped resolved equity is an explicit additional residual in the issuer view/export, with source drill-down.

Golden synthetic math: direct NVIDIA $30,000, fund A $50,000 × 8%, fund B $20,000 × 6%, and other direct equity $100,000 yield **$35,200 / 17.6%**, while owned NAV remains **$200,000**. A $10,000 partial fund with 92% equity, 5% cash, 3% missing yields $9,200 + $500 + $300. Negative/leveraged/duplicate economic lines and overweight funds remain wholly opaque; nested funds are never recursively expanded.

Authoritative arithmetic uses Decimal precision 80 and unrounded products/decomposition, serialized as strings. The dashboard rounds USD to cents with ROUND_HALF_UP using integer arithmetic. Displayed row sums may differ by up to $0.01 per displayed row; CSV retains exact values. Cash counts once. Foreign/unpriced/unresolved positions remain visible and exclude unknown amounts from the included valued USD subtotal; total portfolio percentages are unavailable on incomplete NAV. Signed positions or NAV ≤ 0 suppress allocation/coverage percentages. Stale last-good quotes/compositions remain usable with visible dates/warnings; attribution coverage describes resolved equity, separately from valuation completeness.

`POST /v1/portfolio/reports` creates a durable private artifact and small `portfolio_calculations` metadata row. PostgreSQL captures inputs under REPEATABLE READ; DSQL uses its transaction snapshot. The artifact freezes account/position revisions, quote IDs, fund snapshot IDs/raw composition, issuer mappings, freshness/source-priority settings, input hash, calculation version and contribution graph. `GET /reports/{id}`, `/rows`, `/breakdown/{target}` and `/export` under the portfolio prefix read that artifact without recalculating. Browser paths add `/api` and Vite removes it. URL `?report=<id>` restores the same report after reload; refresh creates a new ID. Missing/corrupt artifacts return a recoverable 404, never silently substitute new inputs. Back up the database and PRIVATE_FILE_DIR together. CSV guards formula-like text while retaining signed numeric values.

Selection settings: `QUOTE_STALE_DAYS=7`, `MANUAL_FUND_STALE_DAYS=30`, `ISSUER_FUND_STALE_DAYS=7` (nonnegative integers); optional comma-separated `QUOTE_SOURCE_PRIORITY` (default `manual,cached`) and `FUND_SOURCE_PRIORITY` match exact source labels. Latest eligible as-of wins; quote ties use explicit reviewed overrides, then source priority and stable ID. Fund ties use source priority, publication date and stable ID. Policies are frozen in every report. Capture limits: 10,000 positions, 10,000 observations per security/fund, 50,000 contributions, 20 MB artifact. Smaller account selections provide the recovery path.

Review row drafts retain their starting review revision across refetches. Save or explicitly discard pending corrections before acceptance/publication. A stale draft receives 409; retry requires reviewing refreshed evidence. Mixed account/date source rows and transaction import mode are rejected. Original source files, raw rows and before/after correction audit events remain private.

## Running and verifying Stage 1

Use the root README local setup (`docker compose up --build -d`, `uv run --directory services/api --locked alembic upgrade head`, `pnpm dev:web`) or an existing PostgreSQL 16 server with DATABASE_URL. Host API: `uv run --directory services/api --locked uvicorn app.main:app --host 127.0.0.1 --port 8000`. Apply all migrations through `0006_portfolio_reports`. PostgreSQL Alembic and independent versioned DSQL migration steps remain separate; previously applied migrations/checksums are immutable. `pnpm api:generate` refreshes contracts; `pnpm check` checks generated freshness, lint/format, types, unit/API tests and build.

Offline browser test setup (installed dependencies and local PostgreSQL 16 required):

```sh
pnpm --filter web exec playwright install chromium
E2E_DISPOSABLE_DATABASE=1 \
E2E_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55432/portfolio_browser_test \
pnpm test:e2e
```

The test server only accepts loopback databases ending `_test` and the explicit disposable flag; it creates/resets that synthetic database, applies actual Alembic migrations, and starts API 8051/Vite 5179. Never use a personal database for tests. The suite aborts external browser requests and creates the complete golden portfolio through local UI review/publication, drill-down and CSV export, then verifies frozen-report reload and owned values. CI runs this after aggregate checks with its own PostgreSQL 16 service. CI execution is not claimed unless observed separately.

PostgreSQL feature checks: `TEST_DATABASE_URL=postgresql+psycopg://... uv run --directory services/api --locked pytest -q`. Tests cover exact golden/residual/signed/zero/currency cases, issuer mapping and quote precedence, filtered exports, report reconstruction/checksum failure, 502-row unpublished recovery and competing account imports. The injected UTC clock keeps report expectations deterministic.

DSQL gate: configure IAM/TLS application and migration roles per docs/07; use an exclusive disposable cluster and set `RUN_DSQL_INTEGRATION=1 DSQL_TEST_CLUSTER=disposable DATABASE_BACKEND=aurora_dsql`. Run the full API pytest suite. Stage 1 adds live tests for golden/frozen reports, 502-row fund publication/dedup/history, interrupted recovery and concurrent account publication. Cleanup removes only newly created IDs in bounded batches. These live tests have **not run** here; PostgreSQL/structural dialect checks cannot validate DSQL production behavior. No cloud resources, live quote adapter, scheduler, PDF/AI parsing, FX conversion or recursive look-through were added.

## Shared-AI architecture reconciliation — 2026-10-02

[ADR 0001](adr/0001-shared-personal-ai.md) reconciles the integration handoff with Stage 1. Finance remains authoritative; generic AI infrastructure belongs in personal-AI. Added an async extraction protocol, source/schema/version candidate envelopes, disabled runtime client and explicit synthetic fake. `PERSONAL_AI_ENABLED=false` is documented and passed through Compose; true fails startup. No Stage 1 consumer, HTTP transport, new finance route, canonical mutation path, migration, frontend or provider dependency was added. Live extraction/research/memory/tools and all real-data authorization/consent/retention controls remain deferred.

Observed checks for this reconciliation:

- Focused boundary/config suite: **24 passed**. Covers disabled runtime, rejected enablement/malformed flags, source/schema/version mismatch, request bounds/unknown fields, isolated fake payloads, omitted content in representations and rejection of invalid candidate fields by the existing finance validator. It does not test a future statement-publication integration.
- `pnpm check`: passed generated OpenAPI/TypeScript freshness, lint, formatting, strict types, **9 Vitest**, **71 API tests / 18 environment skips**, and web production build.
- Full API suite against separate synthetic database `portfolio_ai_seam_gate` on existing local PostgreSQL **16.15**: **81 passed / 8 skipped** (seven credentialed DSQL checks and one SQLite-only concurrency variant). Fresh/populated migrations and Stage 1 publication/report regressions remain passing.
- `git diff --check`: passed. No lockfile changes. The copied local virtual environment and Node dependency directory needed locked reinstall/entry-point repair; dependency versions were not changed.

The existing Starlette/httpx deprecation warning remains. Playwright was not rerun for this backend-seam/docs change; its earlier Stage 1 evidence above remains historical. Remote CI, live personal-AI transport/auth and live DSQL are unverified; production remains gated. For the PG run, use `TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55432/portfolio_ai_seam_gate uv run --directory services/api --locked pytest -q` with an isolated synthetic target. The normal README startup commands are unchanged and require no personal-AI service.
