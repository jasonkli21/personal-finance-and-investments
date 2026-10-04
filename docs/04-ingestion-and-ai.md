# Document ingestion and AI design

**Status:** Stage 1 deterministic imports delivered; Stage 2 text-PDF jobs and reviewed transaction CSVs partially delivered; Stage 5 offline research baseline delivered; AI/OCR/transport remain gated | **Updated:** 2026-10-03

**Stage 1:** reviewed position CSV, generic/iShares fund CSV and SPDR XLSX; no AI consumer.
**Stage 2:** A supported text-layer brokerage PDF can be privately previewed through the existing reviewed position-import workflow. Reviewed transaction CSVs are also delivered. Scanned PDFs, screenshots, broad institution coverage, optional AI and bank connectivity remain pending or gated; see [Stage 2 release status](stage-2-release.md).
**Stage 5:** retrieval and portfolio-aware investment research.  
**Central rule:** extraction is probabilistic; financial records and calculations must be validated and deterministic. Both the local PostgreSQL and production Neon PostgreSQL implementations must preserve identical import semantics; see [`07-postgres-neon.md`](07-postgres-neon.md).

Finance owns private originals, source lineage, institution-specific deterministic parsing/mapping, numeric validation, deduplication, review and publication. `personal-ai-system` owns reusable extraction/OCR/model execution, research/search/evidence retrieval and attributable AI memory. Source provenance still accompanies every finance record; shared evidence infrastructure does not transfer canonical ownership. See [ADR 0001](adr/0001-shared-personal-ai.md).

## 1. Input modes and priorities

| Input | First extraction method | Fallback | Review |
| --- | --- | --- | --- |
| User portfolio CSV | Python `csv` and user-provided column mapping | Institution-specific import template | Map identifiers and choose snapshot semantics |
| ETF issuer CSV | Provider-specific deterministic parser | Manual issuer download upload | Validate weights, as-of and fund identity |
| Brokerage text PDF | Local table/text extraction; institution adapter | Shared extraction via `PersonalAIClient`; manual correction | Verify dates, balances, holdings and discrepancies |
| Scanned PDF / screenshot | Shared generic OCR/extraction, locally hosted where approved | Manual review/correction when service unavailable | Review all ambiguous numbers/identifiers |
| Bank or card CSV/PDF | Deterministic columns/template, then extraction | Optional shared candidate interpretation; finance rules validate | Verify transaction IDs, totals and transfers |
| Website/export | User-supplied exported CSV/PDF; official published documents | Consented account API if later enabled | Do not bypass authentication or anti-bot restrictions |

Generic OCR/Docling runtime is an upstream integration candidate, not a second runtime to build here. [Docling](https://github.com/docling-project/docling) is MIT licensed, but verify **individual OCR/model licenses and redistribution terms**. [PyMuPDF](https://pymupdf.readthedocs.io/en/latest/about.html#license) has AGPL/commercial licensing implications; assess whether to use it before redistribution. `pypdf`, PDF text extraction built into Docling, and standard CSV parsers are alternatives.

## 2. Import state machine

```text
RECEIVED
  -> FILE_VALIDATED (size/type/checksum; isolated private storage)
  -> EXTRACTED (text, tables, optional OCR; evidence map)
  -> INTERPRETED (deterministic finance mapping; optional personal-AI candidate)
  -> NORMALIZED (internal securities, transactions, units/currencies)
  -> VALIDATED (schema, arithmetic, duplicates, conflicts, source date)
  -> NEEDS_REVIEW | REJECTED | READY_TO_COMMIT
  -> STAGED_IN_BATCHES (bounded idempotent writes, not yet visible)
  -> COMMITTED (a short final transaction atomically publishes the accepted revision)
```

Each transition writes an audit event and retained machine-readable diagnostic. Reprocessing uses a versioned parser and creates a new *import attempt*, not a duplicate financial record. This is the planned Stage 2 lifecycle. Stage 1 already implements review/correction/cancel, bounded unpublished staging and atomic publication; actual states/routes are defined by code/OpenAPI and [release evidence](stage-1-release.md). It does not emit a generic audit event for every conceptual transition.

## 3. Canonical structured extraction contracts

Start with separate Pydantic document contracts, not one unbounded generic `FinancialStatement` model.

**Positions document:** `institution`, `account_label_or_mask`, `statement_start`, `statement_end/as_of`, `base_currency`, `positions[] {raw_name, raw_identifier, quantity, reported_price?, reported_value?, currency?, evidence_ref}`, `cash_balances[]`, `reported_total?`, `unparsed_rows[]`, `warnings[]`.

**Transaction document:** `account_label_or_mask`, `statement_period`, `transactions[] {posted_date, transaction_date?, raw_description, amount, currency, raw_type, id_if_present?, evidence_ref}`, `opening_balance?`, `closing_balance?`, `warnings[]`.

**Fund composition document:** `fund_identifier`, `as_of`, `lines[] {raw_security_identifier, raw_name, raw_weight_value, raw_weight_unit, asset_type, raw_row_ref}`, `source_url`, `warnings[]`.

- Values that are genuinely absent remain `null`; do not fill in invented dates, tax basis or tickers.
- Keep **reported** account/statement subtotals separate from **calculated** ones.
- Preserve amount signs and whether a statement reports debits or credits; never silently invert on guesswork.
- Track evidence at page/table/row level where extraction tooling supports it.

## 4. Numeric and semantic validation

- Parse currency, negative numbers, parentheses, thousands separators, fractional shares, percent vs decimal units and statement-specific debit/credit conventions.
- Validate `quantity × reported_price ≈ reported_value` with a configurable tolerance for rounding, stale prices and corporate actions; deviations require review.
- Validate sum of account-level line values vs reported statement total when both exist; non-position items (cash, margin debt, receivables, accruals) must be represented or flagged.
- For fund snapshots, verify fund identity and effective date, parse cash/other/derivative categories, and flag unusual sum of weights; do not force malformed weights to 100%.
- Dedup key combines file hash + account + statement identity for files. For transactions, use native provider IDs if present, otherwise configurable fingerprint plus collision review. Identical recurring purchases may legitimately share date/amount: never dedup on amount alone.
- A later statement is a **replacement position snapshot**; its differences are not automatically treated as trades or gains.
- Source confidence is per-field and from measurable evidence (e.g., exact table mapping, unmatched ticker, arithmetic discrepancy), not a naked model-generated probability.

## 5. Personal-AI integration boundary

`app/integrations/personal_ai.py` exposes `PersonalAIClient.extract(ExtractionRequest) -> ExtractionCandidate`. These finance-owned envelopes identify source, schema and version and carry bounded text/untrusted fields; they are **not** a frozen upstream HTTP contract or complete statement schema. The disabled runtime client makes no calls. The explicit fake is for synthetic tests only. `PERSONAL_AI_ENABLED=true` fails configuration rather than authorizing a public service.

When Stage 2 needs extraction, agree the upstream endpoint/version and bounded document transport, then implement one HTTP adapter with timeouts, response-size bounds, no automatic redirects, safe failure codes and offline contract tests. Do not import upstream Python classes or expose arbitrary local paths over a deployed API. Preserve finance-owned source/field evidence, raw values, dates, unparsed rows and review quality in capability DTOs; do not reuse them as ORM models.

Routing order is deterministic finance parsing, optional approved shared extraction, then manual correction. Upstream chooses allowed local/cloud models and owns prompt/structured-output runtime. Failure cannot silently activate another provider, paid tier or remote processing. Schema-conforming output remains untrusted: finance validates identifiers, arithmetic, provenance and completeness, requires reviewed acceptance, and persists through existing staged publication. Finish external calls and save reusable candidate results before entering DB-only OCC retries.

Research, preference-memory retrieval and read-only finance tools are later capabilities. No generic `run_agent`, plugin registry or write tools are introduced now. App settings/thesis notes remain finance product state; portfolio truth is never AI memory.

## 6. Privacy / provider routing rules

| Data classification | Allowed by default | Requires explicit opt-in | Disallowed by default |
| --- | --- | --- | --- |
| Synthetic sample data | Any approved local or free provider | No | Paid auto-fallback |
| Public issuer fund data / SEC filings | Deterministic local; approved personal-AI if terms allow | Cloud research enabled | Uploading unrelated private account data |
| Actual brokerage/bank statements | Deterministic local tools; shared local extraction after explicit enablement | Specific reviewed provider with conscious consent and data minimization | Unpaid Gemini API, unvetted aggregators or unredacted remote logs |
| Personal transactions / account IDs | Local database and deterministic tools | Separate explicit account connection or compliant paid-service policy decision | Default free-cloud inference |

[Gemini API terms](https://ai.google.dev/gemini-api/terms) as checked 2026-09-25 say submissions to **Unpaid Services** may be used to improve products and reviewed by humans; the app must not send sensitive statements to that tier. Any future service transmission requires explicit scope/consent and reviewed data handling. Deployed private data additionally requires authenticated finance users, authenticated service calls, server-verified owner propagation and authorization at the personal-AI boundary. A localhost URL, API key or fixed `local` owner alone proves none of these. Local trusted mode must also document storage, egress and retention; it is not implemented now. Any future cloud processing policy requires a new privacy review and opt-in. Model output displayed as AI-produced text must cite actual source passages where factual research claims are made.

## 7. UI review and reconciliation

The import wizard shows: input file and detected type; extracted account/date; recognized positions/transactions; unresolved tickers, weak classifications, arithmetic discrepancies; source evidence; and before/after diff. The **Commit** action publishes only after bounded, idempotent staging batches complete; one short final transaction changes the visible revision. Bound rows/bytes and transaction duration to protect memory, latency, retry cost and review usability; never hold a transaction across external parsing or an entire large import. Provide cancel, reprocess with a different parser, explicit overwrite/merge settings, and a per-record correction mechanism. Never hide rows solely because the model cannot parse them.

## 8. Evaluation plan (required before trusting AI)

Finance evaluates field/evidence accuracy, reconciliation and reviewed publication; generic model/extraction/search evaluations are owned upstream. Create a small benchmark of **synthetic or permission-cleared** examples: clean CSV, inconsistent issuer CSV, text PDF with multiple columns, scanned statement, screenshot, negative numbers, fractional shares, duplicated rows, split statement, transfer/credit card payment, and missing lot data. Store manually checked expected structured JSON fixtures.

Measure:

- Exact-match accuracy for date/account/identifier/quantity/amount; field-level precision/recall where appropriate.
- Source-grounded row coverage, total reconciliation errors, false matches, missed rows and duplicate imports.
- Required review rate and human correction time; local inference latency and RAM requirements.
- Failure and cancellation behavior: no unintended canonical data changes.

**Release gate:** all correctness-critical arithmetic is rechecked outside the LLM. A failing or unavailable model must degrade to deterministic/manual import, not block basic holdings management.

## 9. Stage 5 research pipeline

```text
Finance UI selects company/question
 -> Finance computes frozen direct/derived exposure and selects minimal consented context
 -> PersonalAIClient sends a bounded research request under an agreed service contract
 -> personal-ai-system retrieves dated public evidence and synthesizes attributable findings
 -> Finance checks schema, issuer/source identity, citations, dates and deterministic metrics
 -> Finance displays/saves a dated explanatory research result and separate user thesis
```

Generic SEC/IR research ingestion, search, passage indexing, ranking, synthesis and evidence/memory lifecycle live upstream. Finance may retain source references, approved evidence excerpts, returned result snapshots and finance-specific reported-fact validation; this is not a shared database or second research engine. When the service is disabled, finance retains core holdings/import/report functionality and later cached source views/manual notes. AI cannot overwrite canonical holdings, quantities, prices, transactions or tax lots. A research result is separate from a confirmed market observation and attributable preference memory.


Provider-specific dated delivery facts are preserved in [the pre-migration snapshot](history/pre-gcp-neon/04-ingestion-and-ai.md). [ADR 0002](adr/0002-gcp-neon.md) and the [migration record](gcp-neon-migration.md) define the current architecture; this plan does not claim additional product completion.
