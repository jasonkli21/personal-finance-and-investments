# Stage 1 implementation plan

**Status:** Proposed execution backlog, not implemented  
**Updated:** 2026-10-02 — reviewed against Stage 0 commit `81b220e`
**Roadmap coverage:** 1.1 Owned positions/valuation; 1.2 ETF composition; 1.3 Look-through/dashboard

This is the execution plan for the first useful release: owned stocks, ETFs, and cash across accounts, plus a separate, reconciled company-exposure view. Read [the product specification](01-product-spec.md), [architecture](02-architecture.md), [data-source policy](03-data-sources.md), [ingestion rules](04-ingestion-and-ai.md), and [DSQL contract](07-aurora-dsql-compatibility.md). [Stage 0](stage-0-implementation-plan.md) supplies the local foundation; its real-DSQL gate remains required before production.

## Scope boundary

Stage 1 includes account management, reviewed replacement position CSVs, dated manual/cached valuation, manual fund CSVs, two verified official issuer full-holdings formats, one-level ETF decomposition, optional issuer rollups, drill-down, filtering, and CSV export.

The smallest vertical slice is **manual stock + ETF positions → upload dated synthetic fund composition → inspect NVIDIA direct and ETF contributions → reconcile/export**. Affected domains are `accounts`, `securities`, `portfolio`, `prices`, `funds`, a minimal import service, and a pure exposure engine.

PDF/OCR, AI, bank connections, transaction-based performance, tax lots, recursive fund-of-funds traversal, derivative valuation, trading, AWS application hosting, and general background queues are excluded. Nested funds, shorts, and unsupported instruments stay visible with explicit opaque/residual treatment.

## Delivery conventions and cross-cutting requirements

- Reuse Stage 0 domain services/settings; they currently receive SQLAlchemy sessions directly, with no repository-object layer. Extend schema incrementally rather than precreating later-stage domains.
- Imports are previews until the user accepts a particular revision. Account/date position snapshots replace holdings; they are neither purchases nor additive imports.
- Preserve raw rows, identifiers, weight values/units, zero/negative values, and unknown classes. A rejected or unresolved row remains in diagnostics/evidence.
- Download/parse outside database transactions. Stage bounded idempotent batches under unpublished revision IDs, validate completeness, then atomically publish; every normal read filters published revisions.
- Retry only the database unit with a fresh session after a classified OCC failure. Do not repeat external fetches, store duplicate files, or publish twice.
- Keep exact authoritative math in `Decimal`. API decimals are strings, units are explicit, and percentages divide by the stated included portfolio NAV.
- Start USD-only valuation if needed. Retain foreign metadata; absent FX or quotes produces unconverted/unpriced amounts, not a fabricated complete NAV.
- One-level decomposition replaces an ETF's value in the derived composition. It never creates actual positions or changes net worth.
- Verify official access/terms/formats before implementing live adapters and update the source register. Existing shortlist dates are not new verification evidence.
- CLI/manual refresh is sufficient; no AI or account API may become a prerequisite for the MVP.

## Review decisions and implementation handoff

These decisions close ambiguities in the original backlog. They are implementation requirements, not delivery evidence.

### Prerequisite and major commit sequence

Stage 0's latest local gate is still unverified. Before Stage 1 code changes, execute its PostgreSQL 16 fresh-install and populated `0002 → head` upgrade tests, replacement/history/rollback, draft-conflict tests, and generated-contract checks. The upgrade test begins at 0002, while the fresh install exercises 0001 through head; do not describe the populated fixture as starting at 0001. Obtain an isolated PostgreSQL 16 runtime locally or actual CI evidence for this checkout. Docker/psql are absent and `gh` is unauthenticated in the review environment; a configured workflow is not a successful run. Fix only necessary prerequisite defects and record commands/results. DSQL access is a separate production gate and does not block local Stage 1.

Implement and commit three major packages, rather than one commit per dotted subtask:

| Commit | Scope | Validation before committing |
| --- | --- | --- |
| Prerequisite, only if fixes are needed | Stage 0 local gate remediation | Real PG16 gate and existing aggregate checks |
| **S1.1 Owned portfolio, valuation and reviewed position imports** | S1.1.1–S1.1.3, catalog authoring, shared private file/review/batch infrastructure; S1.1.4 is optional | Owned/selection, review correction/cancel, duplicate/replacement/concurrency, PG16 migration and generated contracts; runnable UI slice |
| **S1.2 Fund composition and issuer formats** | S1.2.1–S1.2.2, history/review UI, source verification and permitted refresh/upload paths | Both official-format parser contracts, manual mapper, anomalous/raw preservation, PG16 batches/publication, generated contracts |
| **S1.3 Reconciled exposure, dashboard and first release** | S1.3.1–S1.3.3, frozen reports, export, complete offline browser journey and release documentation | Golden math, report consistency, PG16 feature suite, Playwright and aggregate checks |

Keep each package coherent; include its migrations, generated contracts and documentation in that commit. Existing applied Alembic files and recorded DSQL step checksums remain immutable. Maintain a release evidence record (for example `docs/stage-1-release.md`) listing package commit IDs, commands/results and unresolved live-provider/DSQL gates. A documentation-only evidence follow-up is acceptable if the final commit ID cannot be recorded within itself. Do not push, deploy, create paid resources, or implement later stages merely to complete Stage 1.

### Deterministic selection and financial policy

| Concern | Stage 1 decision |
| --- | --- |
| Default owned selection | Use each included active account's selected published pointer, shared by manual and imported writes. Both advance the same account counter. Archived accounts are excluded by default; explicit history inclusion is labelled and archived accounts reject writes. No account hard-delete workflow. |
| Explicit `as_of=T` | Choose published position history with effective time ≤ T, latest effective time then highest account revision as tie-breaker. Include superseded published history; exclude unpublished/cancelled revisions. This is a snapshot inspection, not performance reconstruction. Default selection and historical selection are distinct modes. |
| Quotes | Eligible observations match security/currency, are accepted and dated ≤ valuation time. Latest as-of wins; at equal time choose explicit reviewed manual override, then configured provider priority, then a stable observation ID. Snapshot reported prices are line-scoped fallbacks, not global manual overrides affecting another account. Retain conflicting observations; same source/time with changed content must not overwrite old accepted values. |
| Fund selection | Latest published holdings as-of ≤ valuation time; ties use explicit reviewed source priority and publication revision/ID. Retain revised same-date source files. Stale last-good data is usable with a warning; fetching does not invent an effective date. |
| Default dates | Use an injected UTC clock for report valuation/generation, serialize timezone-bearing timestamps, and show each account's separate position date. Future-dated selected positions cannot silently join an earlier valuation: exclude and warn. Date-only positions use the existing midnight UTC convention. |
| Currency and incomplete NAV | USD-only, with all non-USD/unpriced rows retained and excluded with reasons. Return `included_valued_nav` plus completeness state; only call it total portfolio NAV when complete. On incomplete valuation, percentage of total portfolio is null; a separately labelled percentage of included valued USD assets may be shown. Unknown unpriced value has no fabricated dollar residual. |
| Signed owned values | Preserve negative/zero quantities and cash. Reconcile signed dollar values, but suppress portfolio percentage/coverage metrics when NAV ≤ 0 or signed positions would make an allocation metric misleading. State the unsupported signed-allocation condition. |
| Numeric policy | Preserve existing quantity/value `NUMERIC(28,10)`, price `NUMERIC(24,10)` bounds. Use weights with 10 decimal places and explicit input units. Reject nonfinite/out-of-range/excess-scale normalized inputs with retained raw evidence; never silently truncate. Use Decimal context precision ≥ 80 and test aggregate/product bounds. Compute exposure without intermediate cents rounding; if persistence/export quantizes components, allocate and identify any rounding remainder so reconciliation remains exact at the stored scale. Display USD to cents with ROUND_HALF_UP; displayed row sums may differ by ≤ $0.01 × displayed row count and must explain this. Golden fixture is exact. |
| Anomalous fund | Negative weights, derivatives/leverage, duplicate unresolved economic lines, or reported total > 1 trigger whole-fund opaque fallback. Retain all source rows/diagnostics; do not manufacture a negative missing-weight bucket or normalize. For otherwise supported total ≤ 1, decompose recognized equity, cash and nested/other/unknown weights and assign `1 − reported_total` to missing weight. Zero rows remain visible. |
| Coverage | Security attribution counts resolved supported equity value; issuer attribution additionally requires a reviewed issuer mapping. Cash is a separate reconciled category, nested funds remain opaque, and unknown/other/missing weights are residual. Publish the numerator/denominator and distinguish attribution from valuation completeness. On the 92% equity/5% cash/3% missing fixture, security coverage is 92%, with all three parts reconciling. |
| Filters | Account inclusion determines NAV. Security/issuer/source search and top-N only filter report rows; they never silently change the denominator. Include hidden-row/subtotal metadata. One-level nested ETFs have their own opaque category, not an operating-company exposure. |

Default stale thresholds must be explicit configuration, documented by provider and tested with an injected clock; they are application policy, not claims about verified vendor freshness.

### Review, identity and publication

- A position import targets exactly one internal account and one date. Require the mapped account/date values to match the confirmed target; reject mixed-account/mixed-date files. Empty replacement requires explicit clear-account confirmation. Cash uses explicit `cash:USD` (or another currency) and quantity as balance with no price; document optional `asset_type`/identifier namespace/exchange columns. Reject transaction mode. Duplicate position security rows require user correction rather than automatic sum.
- Unmatched/ambiguous **position** rows block commit until resolved; foreign-currency rows can be retained canonically with exclusion labels. Fund constituents may stay unresolved and publish to residual after explicit review. Provide reviewed local security creation (type/name/currency and scoped identifiers) and issuer mapping from an empty catalog; never create securities or merge companies merely from parser guesses. No external catalog API is required.
- Provide correction/remapping, explicit acknowledgement and cancellation API/UI actions, not only preview and commit. Corrections require the expected review revision, create audit history with a reason, and invalidate earlier approvals/batches. The client captures review and account revisions with the draft; background refetch cannot rebase them. Cancelled attempts cannot publish.
- File/source/account-or-fund/effective-date identity identifies duplicate source input; parser version/mapping/review payload hashes identify attempts. Return an earlier accepted result for an unchanged duplicate **without moving a newer account pointer backward**. Changed interpretation of already-published bytes requires explicit correction/replacement and new immutable revision; never silently ignore or republish a revised mapping. A reused idempotency key with a different payload returns conflict.
- All reads filter published lifecycle, not only the literal `accepted` status: superseded published history remains inspectable. Staging and final publication revalidate target identity, active account, review revision, exact row/batch hash counts and financial validation. The final DB-only transaction compares the captured account head/review revision and moves visibility once; stale conflicts return HTTP 409 without automatic rebase. Concurrent duplicate commits must return one canonical result.
- Apply safe row **and byte** budgets to raw review rows, canonical lines, indexes and audit writes. Default batches should be at most 200 rows and comfortably below DSQL limits; test ≥ 500 lines across multiple commits and interruption/retry/cancel. Publication must update bounded metadata only, not all staged lines. Raw full-file evidence lives in private storage; bounded row evidence may live in SQL. A local cleanup CLI may remove orphaned unpublished batches/files after a documented grace period, never referenced accepted/history/report artifacts.
- Official format parsing is mandatory for two issuers, but automated network retrieval is conditional on verified permitted access. Default candidates are iShares IVV and SPDR SPY. If automation is restricted, finish the adapter using official-download upload plus current source/rights evidence and an explicit unavailable-refresh reason; this is the plan's permitted fallback, not permission to bypass restrictions. Do not claim automated refresh or live success from parser fixtures. New public downloads still require preview/accept unless a distinct trusted path is explicitly approved.

### Frozen report and private-input boundaries

A report must survive a later portfolio edit, new quote, fund publication, issuer remapping or application restart without changing its drill-down/export. Add an immutable calculation record with a UUID, methodology version, filters, selected IDs, currency/status, and hash of normalized inputs including issuer mappings and policy settings. Persist the frozen inputs/results in bounded SQL records or a checksummed private derived artifact referenced from SQL. Avoid an unbounded JSONB payload or process-memory-only cache. Report generation resolves inputs in a consistent DB read transaction, then calculates outside write transactions; no provider calls occur during report generation. Failed report persistence returns a safe error, never a report ID pointing at a different calculation.

Owned/exposure pagination, breakdown and CSV require the same calculation ID. Refresh explicitly creates a new report. Verify old report contents after changing every source type and after process restart. Source IDs alone are insufficient if issuer mappings or selection policies can mutate; freeze those values too. A missing/expired report must return an actionable 404/410, never transparently recompute under the old ID. Reports are derived artifacts, not additional authoritative holdings.

Private uploads use generated keys, owner-only directories/files, atomic file writes/hash verification, and no user-supplied paths or public static mounts. Bound bytes, rows, fields, parser work and encodings; support UTF-8/BOM, quoted fields and CRLF, reject binary/HTML masquerading as CSV. MIME is evidence, not a sole acceptance check. Network adapters enforce exact destinations and redirect allowlists, disallow private/loopback destinations, cap response sizes/time and respect permission failures/Retry-After. Neutralize CSV formula injection only for textual cells; preserve legitimate signed numeric decimals. Test these boundaries with synthetic inputs and avoid raw financial content in logs.

## Required verification matrix

| Area | Required fixtures / failure cases | Evidence |
| --- | --- | --- |
| Accounts/positions | Same security in two accounts, fractional/zero quantities, cash, account archive/position removal | Domain, API, PostgreSQL, browser |
| Snapshot import | Duplicate file, 10→12 replacement, unresolved row, correction, conflicting revision, interrupted batch | PostgreSQL plus real DSQL before promotion |
| Review/catalog | Empty catalog, ambiguous scoped ID, duplicate position rows, mixed account/date, correction after approval, cancellation, duplicate after newer head | Domain/API/UI and PostgreSQL |
| Quotes/FX | Missing/stale/manual/conflicting observations, unavailable FX, quota/outage | Offline fake-provider and selection tests |
| Fund formats | Percent/decimal weights, missing date, unknown class, cash, nested fund, short, weight total anomaly | Synthetic parser contracts, changed-format rejection |
| Exposure | Golden NVDA, share classes, incomplete/opaque fund, rounding, zero/negative NAV, account filters | Pure Decimal unit tests and both SQL targets |
| Frozen report | New quote/fund/account head/issuer mapping after generation, server restart, pagination/search, missing artifact, text formula export vs signed numeric cells | PostgreSQL/API and browser |
| Input limits | UTF-8 BOM/CRLF/quotes, invalid/binary/HTML content, excessive bytes/rows/fields, unsafe file name, disallowed redirect, cleanup of referenced artifacts | Offline parser/storage/fake-HTTP tests |
| Release journey | Create/import → compositions → drill-down → CSV; no provider keys | Playwright offline smoke |
| Production | Fresh/upgrade migrations, FKs/index readiness, 500-row import, OCC and publish concurrency | Gated real DSQL; skipped means unverified |

## Required implementation artifacts

**Required persistent extensions:**

| Record | Required fields / invariant |
| --- | --- |
| File / import attempt | UUID, private key/hash/size/type, source, account or fund scope, effective date, parser version, attempt/status, safe diagnostics; duplicate identity distinct from parser attempt |
| Staging revision / batch | Import/snapshot UUID, ordinal, payload hash, row counts, state, review revision, timestamps; unique batch identity prevents retry duplication |
| Raw/review line | Raw row/identifier/class/values/units, evidence reference, normalized values, nullable matched security, match/review status, correction reason |
| Fund snapshot | Fund security, as-of, fetched time, source URL, content hash/file, parser version, reported/recognized weights, warnings, publication state |
| Fund line | Snapshot, stable line identity, nullable constituent security, raw identifier/name/class, decimal weight, original weight unit/value, match status |
| Manual override | Target field/revision, previous observation reference, accepted value, reason, actor/source, effective and recorded times |
| Frozen calculation | UUID, methodology/policy/filter manifest, input/output hash, selected IDs and frozen issuer mappings, bounded immutable rows or private artifact key; stable drill-down/export across restart |

**Required API and derived contracts:**

| Route under backend `/v1` (browser `/api/v1` through existing Vite proxy) | Contract |
| --- | --- |
| `/accounts` and `/accounts/{id}/positions` | Stage 0 account/manual workflows extended to stocks/ETFs/cash and archive rules |
| `POST /securities`, reviewed identifier/issuer mapping actions | Local catalog authoring from an empty database; conservative matching, expected revision and audit reasons |
| `POST /imports/positions/preview` | Private CSV receipt, mapping and explicit target account/date/snapshot semantics; no canonical change |
| `GET /imports/{id}` | Reviewed rows, diagnostics, before/after diff, state and revision |
| `PATCH /imports/{id}/review`, `POST /imports/{id}/cancel` | Mapping/row corrections and acknowledgements with expected review revision; invalidate earlier approval; cancellation cannot publish |
| `POST /imports/{id}/commit` | Expected review/target revision and idempotency key; staged, validated, atomic publish |
| `/funds/{security_id}/snapshots`, `/upload`, `/refresh` | Dated history, reviewed manual import, bounded allowlisted refresh |
| `/market-data/quotes/status` | Missing/stale/manual/source status; optional manual quote write contract |
| `/portfolio/owned` | Account/as-of/currency filters, published positions, valued/unpriced parts |
| `/portfolio/exposure` and `/{id}/breakdown` | Security/issuer level, contributions, NAV basis, residual/coverage/freshness |
| Portfolio CSV export | Same frozen calculation identity/filters and source dates as displayed report |

Finalize concrete catalog, report creation/retrieval, pagination and manual quote routes in OpenAPI while preserving existing `/v1` routes and the proxy. Do not change the API prefix solely to match the earlier illustrative `/api/v1` table. All decimal fields remain strings, including coverage and percentage values.

Exposure responses must identify `calculation_version`, generation/valuation times, selected position/quote/fund snapshot IDs, reporting currency, included accounts, NAV status, direct/indirect/residual amounts, attribution coverage, and warnings. Account/fund contribution rows contain their own source dates. Generated TypeScript types/client follow OpenAPI changes.

**Configuration:** manual providers by default; allowlisted funds/provider IDs; provider-specific stale thresholds; quote/request budgets; timeout/response/upload limits; batch row/byte bounds; capped DB retries; currency/rounding tolerance policy. Exact names must be recorded at implementation handoff.

## Dependency map

```text
Stage 0 local gate ─> S1.1.1 Fixtures/contracts ─> S1.1.2 Owned/valuation ─> S1.1.3 Position CSV
S1.1.1 + S1.1.3 shared publication ──────────────> S1.2.1 Fund import ─> S1.2.2 Issuer adapters
S1.1.2 + S1.2.1 ─> S1.3.1 Exposure engine ─> S1.3.2 Dashboard ─> S1.3.3 Export/release
S1.1.3 + S1.2.2 ──────────────────────────────────────────────────────> S1.3.3
S1.1.2 ─> S1.1.4 Optional quote adapter ───────────────────────────────> S1.3.3
real DSQL schema/import/exposure suite ───────────────────────────────> production gate only
```

Manual valuation supports the entire offline release path. The optional live quote adapter must not delay it.

---

## Stage 1 — Portfolio MVP

### S1.1.1 — Establish portfolio fixtures, policies, and contracts

**Dependencies:** Stage 0 local completion.  
**Modules:** portfolio, prices, funds, securities; fixture/API schemas.

**Goal:** define measurable financial behavior before connecting providers.

**Work:**

1. Create the golden $200,000 portfolio: $30,000 direct NVDA; $50,000 ETF A with 8% NVDA; $20,000 ETF B with 6%; $100,000 other assets with no NVDA.
2. Add incomplete fund (92% recognized, 5% cash, 3% residual), opaque ETF, multiple accounts, issuer share classes, zero quantities, unknown identifiers, unsupported negative/leverage lines, and missing quote/FX fixtures.
3. Record accepted policies for snapshot precedence, user review, quote selection, stale thresholds, issuer mapping, currency scope, Decimal precision, and reconciliation tolerances.
4. Specify domain records, import/quote/fund interfaces, OpenAPI errors, and calculation provenance; supply deterministic fakes and an injected clock.

**Requirements:** fixtures are synthetic; percentages have explicit units; absent fields stay absent; tolerances distinguish internal exact math from display rounding. Start with exact Decimal comparison for the golden fixture and document any export/display tolerance separately.

**Acceptance criteria:** contracts express actual versus derived values, priced versus unpriced totals, selected snapshot IDs, and per-source dates; expected NVDA is exactly $35,200/17.6%; actual NAV remains $200,000; no fixture depends on a live provider.

**Out of scope:** historical returns, lot schemas, or silent assumption of daily/intraday fund composition.

### S1.1.2 — Extend owned positions and dated valuation

**Dependencies:** S1.1.1.  
**Modules:** accounts, securities, portfolio, prices; web owned view.

**Goal:** answer what the user actually owns and what can be valued reliably.

**Work:**

1. Extend manual create/edit/remove snapshots to equity, ETF, cash, zero/fractional quantities, and explicit manual prices.
2. Implement quote observation/selection behind a `QuoteProvider` interface, with manual and cached implementations first. Preserve conflicting observations and the selected precedence.
3. Compute dated position/account totals in a domain service; keep cash balance handling separate from equity multiplication.
4. Expose owned positions with account filters, quote/source dates, stale flags, unavailable values, and explicit currency exclusions; build sortable accessible tables.
5. Define account archive behavior and as-of selection without deleting historical data or choosing future-dated observations silently.

**Requirements:** foreign amounts cannot join USD totals without a dated conversion; any incomplete valuation labels denominator/completeness explicitly. Unsupported assets still appear. Manual edits do not create purchase cost or tax history.

**Acceptance criteria:** two accounts remain independent after edit/remove; cash counts once; missing quotes do not become zero; future/mismatched-currency quotes are rejected by selection; reload preserves accepted positions and manual price provenance.

**Out of scope:** real-time quotes, historical performance, authoritative float math in UI, and fund decomposition.

### S1.1.3 — Implement reviewed position-CSV snapshot imports

**Dependencies:** S1.1.1, S1.1.2.  
**Modules:** minimal imports, private storage, securities, portfolio; import wizard.

**Goal:** replace account holdings safely from a user export.

**Work:**

1. Publish a canonical CSV template: account, ticker/identifier, quantity, optional price, currency, as-of; support explicit column mapping and source/account/date confirmation.
2. Validate upload bytes/size, retain private original/hash, parse rows outside transactions, and preserve raw data plus unknown identifiers and diagnostics.
3. Show a before/after diff against the selected account revision. Require resolution of unmatched/ambiguous position rows before commit; never hide rows from the review. Implement correction/remapping/acknowledgement and cancellation with captured review revisions.
4. Deduplicate by content hash plus source/account/snapshot identity; parser-version reprocessing creates another attempt without another financial snapshot.
5. Stage bounded hashed batches under a pending revision, verify reviewed counts/totals, and publish in one short expected-revision transaction.
6. Make commit retries return the accepted result; interrupted staging/cancellation keeps the prior portfolio visible and permits safe recovery.

**Requirements:** snapshot versus transaction semantics are explicit; Stage 1 supports snapshot imports and rejects a requested transaction mode as unsupported. Corrections invalidate old review approval. Two concurrent imports cannot both silently replace the same account head.

**Acceptance criteria:** same file twice does not multiply holdings; a later file changes 10 shares to 12, not 22; old history remains; malformed decimal/date, unmapped identifier, changed review revision, failed batch, duplicate commit, and OCC retry leave no visible partial snapshot.

**Out of scope:** inferring trades from snapshot differences, PDF extraction, trusted auto-commit, and institution login.

### S1.1.4 — Add one optional verified quote source

**Dependencies:** S1.1.2; source/terms/cost verification.  
**Modules:** price provider adapter, refresh CLI/status UI.  
**Decision required:** provider credentials and allowed usage if no suitable free source is available.

**Goal:** improve convenience without weakening offline valuation.

**Work:** verify one official provider against the source register; implement bounded requests, timestamp/currency normalization, cache identity, timeout/backoff/`Retry-After`, and quota accounting; persist observations after fetching; document a synthetic opt-in smoke procedure and manual fallback.

**Requirements:** no claim of real-time data unless the selected licensed endpoint provides it; no automatic paid fallback; credentials server-side; no repeated provider calls during DB retry. An unavailable provider cannot erase manual/cached values.

**Acceptance criteria:** fake-provider tests cover success, malformed payload, permission failure, rate limit, timeout, unchanged observation, and outage; cached data becomes visibly stale; disabling the adapter leaves owned/exposure workflows working; current verified terms and actual smoke status are documented.

**Out of scope:** streaming feeds, multiple competing quote integrations, and using an unofficial endpoint as the sole dependency.

### S1.2.1 — Implement manual fund-holdings import and identity review

**Dependencies:** S1.1.1 and S1.1.3's shared import publication boundary.
**Modules:** funds, securities, private import storage; composition review.

**Goal:** make ETF decomposition usable entirely offline.

**Work:**

1. Define `FundHoldingsProvider` output with fund identity, source, reporting/fetch dates, parser version, raw hash, lines, reported units, and completeness diagnostics.
2. Add a generic user CSV mapper with required explicit as-of and weight units; user uploads remain user-provided rather than issuer-verified.
3. Resolve scoped ticker/exchange, CUSIP, ISIN, and provider identifiers conservatively; preserve share classes separately and curate optional issuer mappings with review/source metadata.
4. Persist immutable dated snapshots/lines with raw zero/negative/unknown categories; report recognized, cash, nested/unsupported, and missing weights separately.
5. Use bounded unpublished batches and atomic publication; expose history and the exact snapshot selected for a report.

**Requirements:** a top-ten file is incomplete, never full composition; absent date/fund identity/units requires review or rejection. Duplicate raw rows are diagnosed rather than blindly merged. No normalization to 100%.

**Acceptance criteria:** repeated upload is idempotent; two dates retain both snapshots; an unmapped constituent remains in the source/review and residual output; 8% and 0.08 convert once; missing date, 105% total, cash, nested ETF, and short lines produce explicit quality states.

**Out of scope:** creating tradable constituent holdings, automatic share-class merging, and recursive traversal.

### S1.2.2 — Add two official issuer formats and bounded refresh

**Dependencies:** S1.2.1; current official source verification.  
**Modules:** two fund adapters, refresh CLI, freshness/status UI.

**Goal:** retrieve supported full holdings with explainable dates and failures.

**Work:**

1. Evaluate the proposed iShares and SPDR formats against current official full-holdings downloads, fund-versus-index identity, permitted access, identifiers, dates, and redistribution constraints.
2. Implement one deterministic parser per verified format; use synthetic or permission-cleared fixtures with metadata/header/trailer changes and unknown instruments.
3. Add allowlisted destinations/funds, bounded redirect/response/time limits, conditional caching, content hashes, and provider-specific cadence/backoff.
4. Fetch outside transactions; run the same validation/publication path as manual uploads and retain diagnostics when a format changes.
5. Document on-demand/local scheduled refresh and last-good cached fallback; if automated retrieval is unsuitable, use the permitted official-download/upload route and record the limitation.

**Requirements:** Stage 1 targets two official issuer formats plus generic manual CSV; substitution requires source-policy evidence, not scraping around restrictions. Reject HTML/login/error content masquerading as CSV. Do not treat fetch time as holdings-effective date.

**Acceptance criteria:** format fixtures yield attributable dated full snapshots; format drift, wrong fund, missing as-of, quota, permission, and outage preserve last accepted data; unchanged content/as-of does not create duplicates; source register lists check date, rights, cadence, credentials, and fallback for each adapter.

**Out of scope:** broad ETF coverage, mandatory Vanguard/QQQ/N-PORT support, and intraday composition promises.

### S1.3.1 — Implement deterministic security and issuer exposure

**Dependencies:** S1.1.2, S1.2.1.  
**Modules:** pure exposure calculation, portfolio/fund read repositories.

**Goal:** explain company exposure while preserving owned NAV.

**Work:**

1. Freeze account position revisions, quote selections, and fund snapshots into a calculation input with currency, valuation date, and methodology version.
2. Compute direct security values and one-level `ETF value × weight` contributions; roll up share classes to issuer only after security calculations.
3. Keep explicit cash, unknown, nested/unsupported, and missing-weight residual components. An ETF without eligible composition stays entirely opaque in decomposition while remaining owned NAV.
4. Define coverage as the stated successfully attributed portion of included valued NAV; report priced/converted coverage separately so these metrics cannot be confused.
5. Validate `direct + indirect decomposition + residual = original included portfolio value` and retain the contribution graph used in drill-down/export.

**Requirements:** never add ETF owned value and constituent values together in the derived composition; never add derived exposure to actual net worth. Anomalous signed/leverage weights remain raw and visibly unsupported; select an opaque fallback or labelled diagnostic treatment with reconciliation, never a normalized allocation. Undefined percentages for zero/negative or incomplete denominators remain explicit.

**Acceptance criteria:**

- Golden NVDA is $30,000 + $4,000 + $1,200 = $35,200, exactly 17.6%; owned NAV stays $200,000.
- $10,000 in the incomplete fund yields $9,200 recognized, $500 cash, $300 residual without scaling weights.
- Account filtering, issuer rollup, opaque funds, stale snapshots, zero NAV, missing FX/quotes, and unsupported signed holdings retain explicit provenance/quality and reconcile under the documented policy.
- Internal exact totals and display/export rounding are tested independently; drift beyond tolerance fails visibly.

**Out of scope:** nested fund recursion, performance attribution, inferred securities, and trading advice.

### S1.3.2 — Build owned/exposure views and source drill-down

**Dependencies:** S1.3.1; generated OpenAPI client.  
**Modules:** portfolio routes, web tables/charts, filters and review links.

**Goal:** make the calculation inspectable by a user.

**Work:** expose bounded/paginated owned, security/issuer exposure, and contribution routes; build separate `Owned positions` and `Look-through exposure` views; add account/security/issuer/source filtering, top-N sorting, selected snapshot dates, coverage/freshness badges, and each contributing account/fund row. Use TanStack Table/Query and ECharts only where a chart helps; offer equivalent accessible tables.

**Requirements:** drill-down/export reuse the same calculation identity as the parent report; a refresh creates an explicit new calculation rather than mixing versions. No color-only quality state. Empty, loading, stale, unpriced, residual, unsupported, and recoverable error states are visible and keyboard accessible.

**Acceptance criteria:** NVIDIA drill-down sums to its row; switching accounts changes the stated denominator/contributions consistently; share-class/issuer toggles preserve totals; unknown exposure is visible; a provider outage displays cached dates and warnings; direct holdings remain unchanged after all derived-view interactions.

**Out of scope:** generic finance dashboards, quote streaming, mobile-native UI, and hiding discrepancies behind charts.

### S1.3.3 — Export, evaluate, and verify the first release

**Dependencies:** S1.1.1–S1.1.3, S1.2.1–S1.2.2, S1.3.1–S1.3.2; S1.1.4 only if enabled.  
**Modules:** CSV export, Playwright, integration fixtures, release docs.

**Goal:** deliver a reproducible offline MVP and an honest production gate.

**Work:**

1. Export owned/exposure rows including source dates, currency, calculation version/identity, accounts, residuals, and unavailable status; neutralize spreadsheet formula injection in textual cells.
2. Run the offline Playwright journey: create accounts → enter/import positions → upload ETF fixtures → select NVIDIA → inspect contributions → export.
3. Run PostgreSQL integration checks for duplicate imports, historical replacement, partial staging, concurrent publication, and deterministic report selection.
4. Execute the real DSQL suite before any production promotion: fresh/upgrade schema, FK/index readiness, Decimal round-trips, 500-row fund batch publication, conflict retries, identical import, and golden exposure.
5. Document actual startup/client-generation/import/refresh/test commands, fixture results, supported funds, precision/tolerances, source verification, and known limitations.

**Requirements:** ordinary CI stays offline; live provider and real DSQL checks are separately opt-in and report skipped status accurately. Exported totals and displayed totals share the same input revisions; no personal statements enter fixtures.

**Acceptance criteria:** a clean local setup completes the journey with no API keys/model; exported golden result matches UI; retry/cancel/failure does not corrupt holdings; all local correctness gates pass; real-cloud gaps are explicit and prevent a production-ready claim.

**Out of scope:** AWS provisioning, Stage 2 imports, and implementing future stages to make the MVP demo work.

## Stage 1 completion review

1. Can users maintain independent accounts and replace snapshots without duplicate assets or inferred trades?
2. Are dated manual/cached prices, unsupported/unpriced assets, and currency limits visible?
3. Do two issuer formats and manual fund CSV preserve all raw rows, dates, and discrepancies?
4. Does the golden fixture produce $35,200/17.6% and preserve $200,000 owned NAV?
5. Do every drill-down, residual, coverage metric, and export use the same source-traceable calculation?
6. Does the full local journey work offline, with no PDF/OCR/AI/bank/AWS dependency?
7. Are real DSQL feature checks passed before production, or explicitly unverified?

Local completion permits Stage 2 or the optional [Stage 4 deployment track](stage-4-implementation-plan.md). Production remains gated on real DSQL and authenticated cloud launch checks.

**Implementation handoff:** record routes/generated-client command, schema/index versions, supported adapters and verification dates, duplicate/revision policies, financial tolerances, golden fixtures, and separately labelled local/provider/DSQL results.
