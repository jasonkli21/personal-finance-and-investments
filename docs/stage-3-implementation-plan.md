# Stage 3 implementation plan

**Status:** S3.1–S3.5 and S3.R complete locally; live Aurora DSQL verification remains
**Updated:** 2026-10-02
**Roadmap coverage:** Work packages 3.1–3.5

This is the execution plan for historical investment analysis, source-backed tax lots, and hypothetical decision support. It consumes reliable [Stage 1 portfolio](stage-1-implementation-plan.md) and [Stage 2 transaction](stage-2-implementation-plan.md) records. Read [the product specification](01-product-spec.md), [architecture](02-architecture.md), [source policy](03-data-sources.md), and [DSQL contract](07-aurora-dsql-compatibility.md) first.

## Scope boundary

Stage 3 adds historical positions/prices/cash movements, documented return calculations where evidence is sufficient, actual-security tax lots and adjustments, explicit hypothetical sale selection, potential wash-sale warnings, before/after exposure/overlap/drift, and assumption-based cash/runway/purchase planning.

The smallest vertical slice is **import synthetic lots for an actually owned equity → compare two lot selections for a hypothetical sale → inspect different estimated gains and post-sale exposure → confirm actual holdings unchanged**. Affected domains are portfolio history/performance, `tax`, simulation/planning, prices/funds, and spending read models.

Order submission, recommendations to trade, tax preparation/filing, tax-certainty claims, inferred lots from aggregate basis, fabricated historical compositions, multi-jurisdiction tax engines, and generalized optimization are excluded. This stage requires no AI provider or production hosting.

## Delivery conventions and cross-cutting requirements

- Keep observations, imported investment transactions, reconciled history, tax-lot evidence, user assumptions, and simulated results separate.
- A snapshot establishes ownership at a date, not acquisitions, contribution history, purchase price, or tax basis. Missing inputs disable dependent metrics rather than invite inference.
- Attach currency/as-of/source/quality to quantities, prices, cash flows, basis, adjustments, and assumptions. Use Decimal throughout authoritative calculations.
- Lot records belong to actual owned securities/accounts. ETF constituents from look-through never become user tax lots.
- Simulations read a frozen input revision and return a derived result. Saving a scenario saves assumptions/result metadata, never accepted position/transaction mutations.
- Version performance and simulation methodologies; disclose fees, timing, FX, price, valuation, and lot-selection assumptions.
- Before implementing tax classification/warning rules, verify applicable official guidance and record jurisdiction, effective period, sources, and limitations. This plan selects no tax rate or legal holding-period threshold.
- Reuse reviewed import publication and bounded retries. Historical recomputation runs outside write transactions; cached results are keyed to evidence and methodology versions.
- PostgreSQL and DSQL share domain formulas; schema/repository/migration behavior needs real DSQL evidence before cloud promotion.

## Required verification matrix

| Area | Required cases | Expected outcome |
| --- | --- | --- |
| History | Deposit/withdrawal, dividend, fee, transfer, split, missing price/event | Explicit reconciliation and gap flags |
| Returns | Flat market with deposit, known synthetic return, missing period, multiple/no numerical roots | No deposit counted as market gain; unavailable/ambiguous return labelled |
| Lots | Fractional shares, missing date/basis, aggregate basis only, adjustments, duplicates | Evidence retained; no fabricated per-lot data |
| Sale | Two bases, partial lots, fees, over-sale, zero/invalid target, price revision | Different estimates; actual state unchanged |
| Warnings | Potential related purchases across accounts, absent coverage, missing dates | Potential/unknown warning, never certified compliance |
| Portfolio scenarios | ETF buy/sell, cash, opaque/overlapping funds, insufficient cash, stale FX | Before/after NAV decomposition reconciles |
| Planning | Empty income history, one-time purchase, variable expense/income, missing dividends | Assumptions and uncertainty visible |
| Persistence | New migrations, scenario save retries, history batches, concurrent edits | PG tests; real DSQL before production |
| UI | Baseline changes, input errors, comparison/export | Stable frozen inputs and clear hypothetical labels |

## Required implementation artifacts

**Required records and contracts:**

| Record | Minimum fields / invariant |
| --- | --- |
| Investment event | Account/security, explicit event type, effective date, quantities/cash/fees/currency, source/import/evidence, review status; distinguish external flows from internal transfers |
| Corporate action / adjustment | Security/account scope, type, dates, ratio/quantity/basis effects where supplied, source/version/review; unsupported effects flag gaps |
| Tax lot | Account/actual security, supplied lot ID, acquisition date nullable, initial/remaining quantity, initial/adjusted basis nullable, basis currency, source/evidence, verified/unknown status |
| Lot adjustment | Lot, quantity/basis deltas, type/reason, effective/recorded date, evidence, revision; audit original values |
| Performance result | Account/period, opening/closing valuations, selected flows/prices, method/version, coverage, exclusions, rounding and convergence status |
| Scenario | UUID/type, immutable baseline revisions, user-entered changes, lot selections, assumptions/currency/times, calculation version/result, status; no canonical write |
| Planning assumptions | Income/expense/dividend inputs, historical sample period, purchase schedule, liquidity restrictions, user overrides, source/uncertainty |

**Required API families under `/api/v1`:**

| Route family | Behavior |
| --- | --- |
| `/portfolio/history` and `/portfolio/performance` | Dated evidence/reconciliation and method-specific return availability |
| `/imports/tax-lots/preview` | Review supplied lot data and position reconciliation; commit through existing import contract |
| `/tax/lots` and adjustment operations | Account/security filters, missing/verified flags, audited reviewed corrections |
| `/simulations/sales` | Explicit quantity/value target, price/fees, selected actual lots, optional illustrative rates; derived estimate |
| `/simulations/portfolio` | Hypothetical buys/sells/cash and before/after actual-security and derived exposure views |
| `/planning/scenarios` | User-defined income/expense/purchase assumptions and sensitivity outputs |

Define exact methods, pagination, scenario persistence, and error envelopes in OpenAPI and regenerate the web client. API decimal strings preserve precision; requests never accept an instruction to execute a trade.

**Configuration/policies:** allowed performance methods and data sufficiency, history price/FX precedence, numeric/convergence bounds, scenario size/quantity/cash rules, fee/rounding assumptions, tax jurisdiction/policy version, illustrative rates supplied explicitly, source freshness, and retention for saved scenarios. No hard-coded promise of tax correctness.

## Dependency map

```text
Stages 1–2 ─> S3.1.1 History contracts ─┬─> S3.1.2 Returns
                                      └─> S3.2 Lots ─> S3.3.1 Sale estimates ─> S3.3.2 Warnings/UI
Stage 1 exposure + history ───────────────> S3.4 Portfolio scenarios
Stage 2 spending + history ───────────────> S3.5 Planning
S3.1.2 + S3.3.2 + S3.4 + S3.5 ────────────> S3.R Evaluation/release
```

Tax-lot simulation can proceed with reviewed lots without waiting for complete performance history. Return availability is independently gated on sufficient evidence.

---

## Stage 3 — Tax lots, history and decision support

### S3.1.1 — Establish historical evidence and reconciliation

**Dependencies:** Stage 1 and Stage 2 local completion.  
**Modules:** portfolio history, prices, ingestion, investment-event repositories.

**Goal:** retain historical facts without manufacturing missing transactions.

**Work:**

1. Define historical valuation/event contracts for purchases/sales when explicitly supplied, deposits/withdrawals, dividends, fees, transfers, and reviewed corporate actions.
2. Extend migrations/repositories with dated events and adjustment evidence; preserve prior snapshots/quote/fund versions and provenance.
3. Map reviewed source events with explicit signs, units, dates, currency and account semantics; retain unknown actions as gaps rather than silently applying them.
4. Reconcile transaction-derived quantities/cash with independent accepted snapshots; present discrepancies and missing intervals for review.
5. Create synthetic time series with known cash movements, fractional positions, missing quotes, splits, fees, and two-account transfers.

**Requirements:** same-day ordering and external-versus-internal flows are documented. Reconciliation cannot rewrite imported snapshots or invent balancing trades. Missing historical ETF compositions prohibit a claim of exact historical look-through.

**Acceptance criteria:** known fixtures reconcile quantities/cash at selected dates; duplicate event imports are idempotent; missing/unknown actions remain flagged; account transfers do not become new total-portfolio contributions; changed history invalidates derived caches without destroying prior evidence.

**Out of scope:** returns, lot reconstruction, and synthetic backfill presented as observed history.

### S3.1.2 — Implement scoped TWR/MWR performance

**Dependencies:** S3.1.1.  
**Modules:** pure performance calculations, history/valuation readers, web performance.

**Goal:** distinguish market performance from cash contributions.

**Work:**

1. Document time-weighted and money-weighted methodologies, period boundaries, cash-flow timing, fees/dividends, reinvestment, FX and account-filter semantics.
2. Implement data-sufficiency checks and pure Decimal calculations; define bounded decimal numerical solving and convergence/multiple-solution behavior for MWR.
3. Calculate only when required valuations/flows exist; otherwise return unavailable/incomplete with missing inputs, or a separately labelled explicitly approved estimate.
4. Expose returns with source IDs, date ranges, method/version, coverage and calculation diagnostics; provide chart/table views and explanatory drill-down.
5. Test known synthetic returns independently of the implementation and compare cash-flow-neutral cases across methods where their scopes permit.

**Requirements:** no binary-float authoritative result; a flat market plus a deposit is not investment gain. Missing subperiod valuation cannot silently become exact TWR; nonconvergent/ambiguous MWR cannot become zero or a guessed percentage.

**Acceptance criteria:** known fixtures match documented tolerances; deposits/withdrawals are treated correctly; missing price/FX/event, zero beginning value, extreme flow, and ambiguous solver cases return clear availability/diagnostics; recomputation with the same inputs/version is deterministic.

**Out of scope:** benchmark-relative advice, fabricated total-return data, and interpreting snapshot appreciation as verified performance.

### S3.2 — Import and maintain source-backed actual tax lots

**Dependencies:** S3.1.1; reviewed import contracts.  
**Modules:** tax lots/adjustments, ingestion, web lot review.

**Goal:** track only acquisition/basis evidence actually supplied.

**Work:**

1. Define migrations and lot/adjustment schemas with nullable acquisition date/basis, explicit currency, fractional quantities, source lot IDs and verification status.
2. Implement reviewed lot CSV ingestion and optional account-provider lot mapping only when the source supplies lots; preserve provided Stage 2 raw lot fields.
3. Reconcile lot remaining quantities against actual position quantity; show unexplained differences rather than filling lots automatically.
4. Apply explicit basis/quantity adjustments with source, date, reason and immutable audit; retain original imported values.
5. Add account/security/verified-status lot views, corrections and duplicate/reprocessing handling through bounded publication.

**Requirements:** aggregate cost basis and an empty provider lot list do not prove individual lots or zero basis. Do not construct lots for ETF constituents. Unsupported corporate actions/adjustments and missing currency remain review items.

**Acceptance criteria:** repeat import does not duplicate lots; two known lots retain independent dates/bases; missing fields remain null/unavailable; partial quantity/adjustments reconcile; an aggregate-only fixture cannot produce a precise lot sale estimate; OCC/review conflicts do not overwrite accepted lot evidence.

**Out of scope:** automatic basis reconstruction, guaranteed brokerage agreement, and preparing tax forms.

### S3.3.1 — Implement explicit hypothetical lot-sale calculation

**Dependencies:** S3.2; Stage 1 valuation.  
**Modules:** pure sale simulator, tax read services, scenario storage if needed.

**Goal:** compare user-chosen lots without changing actual records.

**Work:**

1. Freeze account/security/lot/price revisions and accept a share or amount target, explicit lot selections, fees, valuation date and currency.
2. Validate positive target, available shares per lot, total selection, price availability, lot basis/date completeness, and amount-to-share rounding.
3. Calculate proportional selected basis, proceeds/fees, estimated gain/loss, remaining hypothetical lots, cash and quantities using Decimal.
4. Classify holding periods only under a versioned, officially sourced jurisdiction rule; missing acquisition dates remain unknown. Optional illustrative tax estimates require explicit rates and assumptions.
5. Return/save a reproducible scenario with per-lot breakdown and unavailable portions, never issue a canonical position/lot update.

**Requirements:** high/low-basis ordering is a user-requested comparison, not a recommended trade. Read/simulation services cannot call trade endpoints or canonical write repositories. Reject over-sales/unsupported leverage rather than fabricate shares.

**Acceptance criteria:** with 10 shares at $50 basis/share and 10 at $80, hypothetical sale of 10 at $100 yields $500 versus $200 gain before fees; quantity/basis/fees reconcile for partial lots; missing basis blocks precise gain; actual positions/transactions/lots remain byte-for-byte unchanged across repeated simulations.

**Out of scope:** execution, automatic optimal selection, guaranteed taxes, and tax-lot creation from look-through.

### S3.3.2 — Add qualified warnings and sale comparison UI

**Dependencies:** S3.3.1; applicable official tax-policy verification.  
**Modules:** warning rules, simulation API/client, web lot comparison.

**Goal:** surface uncertainty and potentially relevant imported-account activity.

**Work:** implement bounded evidence-based potential wash-sale checks using configured jurisdiction/rule scope and available imported events; expose relevant dates/security/account matches, uncertain equivalent-security mapping, missing account/history coverage, and rule version; build explicit lot selection, two-scenario comparison, assumptions, and estimated/unknown labels; handle baseline changes by offering a new simulation.

**Requirements:** absence of a detected match is never certification of tax compliance. Do not assert cross-account completeness or legally identical securities from ticker similarity. No hidden model reasoning drives financial/legal classifications.

**Acceptance criteria:** synthetic potentially relevant purchase events trigger a sourced potential warning; incomplete history yields unknown coverage; missing dates/basis remain visible; comparison totals match per-lot results; stale scenario stays tied to its original baseline; invalid/over-sale input is recoverable and no actual state changes.

**Out of scope:** authoritative wash-sale adjudication, tax filing, and assigning legal certainty to incomplete imports.

### S3.4 — Add hypothetical portfolio exposure, overlap and drift

**Dependencies:** Stage 1 exposure; S3.1.1; S3.3.1 when lots are included.  
**Modules:** portfolio simulation, funds/exposure readers, allocation/overlap views.

**Goal:** show how an explicit hypothetical buy/sell changes cash and exposure.

**Work:**

1. Define immutable baseline and user-entered hypothetical trades/cash assumptions; validate quantities, price/fees, currency, and available cash under an explicit financing policy.
2. Compute hypothetical actual positions/cash and call the same versioned exposure engine with dated fund snapshots; keep actual and hypothetical results separate.
3. Document overlap metrics at security/issuer level and distinguish shared constituent membership from shared dollar exposure; opaque fund portions remain unknown.
4. Compute allocation drift against user-entered targets; retain source/version for subjective/custom thematic tags.
5. Expose before/after values, denominator changes, contribution/residual breakdown, fees and data gaps through generated contracts and comparison/export views.

**Requirements:** both sides reconcile actual NAV with derived composition; a pure buy/sell reallocates value with explicit fee/cash effects. Never assume missing historical holdings or quote data. No inferred target allocation or recommended rebalance.

**Acceptance criteria:** hypothetical ETF sale removes its derived contributions and raises cash under the stated price/fee assumptions; buy/fee/opaque-fund scenarios reconcile; insufficient cash/unknown FX produce explicit validation; overlap does not add wealth; saving/rerunning a scenario leaves actual holdings unchanged.

**Out of scope:** optimizer, derivatives leverage modelling, order routing, and speculative nested-fund recursion.

### S3.5 — Add income, runway and large-purchase scenarios

**Dependencies:** Stage 2 reconciled spending; S3.1.1.  
**Modules:** planning domain, finance readers, scenario UI.

**Goal:** explore assumptions about liquidity without overstating predictability.

**Work:** define historical versus assumed income/dividend/expense inputs; select dated analysis periods and explicit one-time/recurring adjustments; distinguish liquid cash, investments, restricted/retirement assets and liabilities; implement bounded period-by-period Decimal cash projection and user-entered purchase scenarios; compare income/expense/dividend assumptions with provenance and sensitivity ranges.

**Requirements:** past dividends/income are observations, not guarantees; missing data stays unknown. Liquidation assumptions must be explicit and cannot silently treat retirement assets as spendable cash or infer taxes. No automatic sale proposal.

**Acceptance criteria:** known constant-cash-flow fixtures match expected balances/runway; one-time purchase reduces cash in its specified period; variable assumptions change outputs transparently; absent income/dividend history does not create forecasts; currencies/liquidity constraints/gaps are visible; canonical balances remain unchanged.

**Out of scope:** guaranteed retirement planning, credit underwriting, personalized trade recommendations, and hidden model forecasts.

### S3.R — Evaluate, document and verify Stage 3

**Dependencies:** S3.1.1–S3.5.  
**Modules:** synthetic evaluations, API/browser integration, release docs.

**Goal:** prove meaningful comparisons and safe separation from actual records.

**Work:** run the two-lot golden comparison and before/after exposure journey; record performance/solver/rounding tolerances and missing-data behavior; execute migration/repository/idempotency/concurrency tests on PostgreSQL and separately on real DSQL before cloud release; verify canonical read-only simulation boundaries; document lot import, methodology/rule sources, scenario retention, client-generation and actual test commands.

**Requirements:** evaluation records identify fixture, schema, calculation and policy versions; authoritative numerical inputs/results stay Decimal. Legal/provider verification is dated at implementation, not assumed from this plan. No private lots/statements enter fixtures.

**Acceptance criteria:** two selections show different gains and reproducible hypothetical exposure with unchanged real holdings; deposits never become market gains; unknown lots/history/FX/warning coverage stay visible; all local tests pass and skipped DSQL checks are reported unverified; regressions cannot be hidden by silently updating expected fixtures.

**Out of scope:** making incomplete source records appear complete or launching AWS resources to declare local completion.

## Stage 3 completion review

1. Is every historical event, lot and adjustment grounded in supplied evidence?
2. Do return methods distinguish cash contributions and disclose insufficient history/solver ambiguity?
3. Can two explicit lot selections produce different estimated gains without actual state changes?
4. Are tax classifications/warnings officially sourced, versioned and appropriately uncertain?
5. Do hypothetical cash/positions/exposure/overlap reconcile and preserve opaque portions?
6. Are planning assumptions, liquidity restrictions, dates and missing coverage visible?
7. Are migrations/retries tested locally and on real DSQL before production?

**Implementation handoff:** publish calculation/rounding/solver policies, event and lot import contracts, rule-source verification, frozen scenario schemas, golden comparisons, client/verification commands, and local versus cloud results. [Stage 5](stage-5-implementation-plan.md) may consume reliable portfolio context without requiring every optional Stage 3 metric.
