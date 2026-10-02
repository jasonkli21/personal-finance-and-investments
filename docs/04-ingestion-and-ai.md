# Document ingestion and AI design

**Status:** Proposed, not implemented | **Updated:** 2026-09-25

**Stage 1:** position CSV and fund-holdings CSV only.  
**Stage 2:** PDF, screenshot, transaction imports, optional AI and bank connectivity.  
**Stage 5:** retrieval and portfolio-aware investment research.  
**Central rule:** extraction is probabilistic; financial records and calculations must be validated and deterministic. Both the local PostgreSQL and production Aurora DSQL implementations must preserve identical import semantics; see [`07-aurora-dsql-compatibility.md`](07-aurora-dsql-compatibility.md).

## 1. Input modes and priorities

| Input | First extraction method | Fallback | Review |
| --- | --- | --- | --- |
| User portfolio CSV | Python `csv` and user-provided column mapping | Institution-specific import template | Map identifiers and choose snapshot semantics |
| ETF issuer CSV | Provider-specific deterministic parser | Manual issuer download upload | Validate weights, as-of and fund identity |
| Brokerage text PDF | Local table/text extraction; institution adapter | Docling for harder layout; local LLM for ambiguous labels | Verify dates, balances, holdings and discrepancies |
| Scanned PDF / screenshot | Docling with local OCR (e.g., Tesseract/RapidOCR) | Optional local multimodal model, if hardware permits | Review all ambiguous numbers/identifiers |
| Bank or card CSV/PDF | Deterministic columns/template, then extraction | Local LLM for unstructured merchant/category mapping | Verify transaction IDs, totals and transfers |
| Website/export | User-supplied exported CSV/PDF; official published documents | Consented account API if later enabled | Do not bypass authentication or anti-bot restrictions |

[Docling](https://github.com/docling-project/docling) is MIT licensed, but verify **individual OCR/model licenses and redistribution terms**. [PyMuPDF](https://pymupdf.readthedocs.io/en/latest/about.html#license) has AGPL/commercial licensing implications; assess whether to use it before redistribution. `pypdf`, PDF text extraction built into Docling, and standard CSV parsers are alternatives.

## 2. Import state machine

```text
RECEIVED
  -> FILE_VALIDATED (size/type/checksum; isolated private storage)
  -> EXTRACTED (text, tables, optional OCR; evidence map)
  -> INTERPRETED (deterministic field mapping; optional local LLM)
  -> NORMALIZED (internal securities, transactions, units/currencies)
  -> VALIDATED (schema, arithmetic, duplicates, conflicts, source date)
  -> NEEDS_REVIEW | REJECTED | READY_TO_COMMIT
  -> STAGED_IN_BATCHES (bounded idempotent writes, not yet visible)
  -> COMMITTED (a short final transaction atomically publishes the accepted revision)
```

Each transition writes an audit event and retained machine-readable diagnostic. Reprocessing uses a versioned parser and creates a new *import attempt*, not a duplicate financial record. Stage 1 may implement a simplified `RECEIVED → PREVIEW → COMMIT` flow, but preserve identifiers so Stage 2 can expand it.

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

## 5. Local model and remote-provider interface

A single app-facing protocol conceptually supports:

```python
class StructuredModelProvider(Protocol):
    def extract(self, text_or_images, schema, context) -> ExtractionResult: ...
    def summarize(self, evidence_bundle, schema, context) -> ResearchResult: ...
```

The actual Python interface may be async and more strongly typed when implemented. Configure the provider via environment and feature settings (`disabled` / `ollama_local` / explicit allowlisted remote). Keep provider credentials server-side; log model ID, provider, prompt/schema version, token/latency usage and redaction status **without logging statement content**.

**Initial model order:**

1. No model: straightforward CSV/text-table parse.
2. Local Ollama model if installed and enabled; schema-constrained JSON + Pydantic validation; choose an appropriately small text or vision model after benchmarking hardware.
3. Optional **user-enabled** remote free API for synthetic, public or thoroughly redacted content; remote processing must never be silently enabled after a local model fails.
4. User correction and saved parser rules on failure.

[Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs) support JSON Schema. This improves format compliance, **not** factual accuracy or numeric correctness. Model names and quantization should be configurable rather than embedded in code.

## 6. Privacy / provider routing rules

| Data classification | Allowed by default | Requires explicit opt-in | Disallowed by default |
| --- | --- | --- | --- |
| Synthetic sample data | Any approved local or free provider | No | Paid auto-fallback |
| Public issuer fund data / SEC filings | Local; approved cloud if terms allow | Cloud research enabled | Uploading unrelated private account data |
| Actual brokerage/bank statements | Deterministic local tools; local Ollama | Specific reviewed provider with conscious consent and data minimization | Unpaid Gemini API, unvetted aggregators or unredacted remote logs |
| Personal transactions / account IDs | Local database and local models | Separate explicit account connection or compliant paid-service policy decision | Default free-cloud inference |

[Gemini API terms](https://ai.google.dev/gemini-api/terms) as checked 2026-09-25 say submissions to **Unpaid Services** may be used to improve products and reviewed by humans; the app must not send sensitive statements to that tier. Any future cloud processing policy requires a new privacy review and opt-in. Model output displayed as AI-produced text must cite actual source passages where factual research claims are made.

## 7. UI review and reconciliation

The import wizard shows: input file and detected type; extracted account/date; recognized positions/transactions; unresolved tickers, weak classifications, arithmetic discrepancies; source evidence; and before/after diff. The **Commit** action publishes only after bounded, idempotent staging batches complete; one short final transaction changes the visible revision. DSQL limits each write transaction to 3,000 modified rows, 10 MiB of changed data and five minutes, so never hold a single transaction across an entire large PDF or ETF import. Provide cancel, reprocess with a different parser, explicit overwrite/merge settings, and a per-record correction mechanism. Never hide rows solely because the model cannot parse them.

## 8. Evaluation plan (required before trusting AI)

Create a small benchmark of **synthetic or permission-cleared** examples: clean CSV, inconsistent issuer CSV, text PDF with multiple columns, scanned statement, screenshot, negative numbers, fractional shares, duplicated rows, split statement, transfer/credit card payment, and missing lot data. Store manually checked expected structured JSON fixtures.

Measure:

- Exact-match accuracy for date/account/identifier/quantity/amount; field-level precision/recall where appropriate.
- Source-grounded row coverage, total reconciliation errors, false matches, missed rows and duplicate imports.
- Required review rate and human correction time; local inference latency and RAM requirements.
- Failure and cancellation behavior: no unintended canonical data changes.

**Release gate:** all correctness-critical arithmetic is rechecked outside the LLM. A failing or unavailable model must degrade to deterministic/manual import, not block basic holdings management.

## 9. Stage 5 research pipeline

```text
User selects company / issuer
 -> Fetch saved portfolio exposure + relevant filing/public news documents
 -> Normalize company IDs, filing dates, source URLs, retrieved dates
 -> Retrieve relevant source passages through a database-neutral `ResearchIndex` (initially metadata filters and portable text matching)
 -> Ask selected provider for a structured, source-referenced summary
 -> Validate that referenced sources exist and quotations are traceable
 -> Present report with actual exposure and source/freshness disclosures
 -> Optionally save thesis note or schedule a future public-data refresh
```

Start with SEC EDGAR and company IR documents. Add licensed/reliable news search only after sourcing, citation and provider limits are tested. First implement fixed workflows; consider LangGraph or multi-agent orchestration only for clearly defined branching workflows. Local PostgreSQL-only `pgvector` may be explored behind `ResearchIndex`, but DSQL production cannot require pgvector or unverified PostgreSQL full-text/index features. Store research outputs separately from verified market/portfolio facts. A model must never overwrite canonical holdings, quantities, prices or tax lots.