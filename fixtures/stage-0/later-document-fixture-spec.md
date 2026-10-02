# Later synthetic document fixture specification

This file describes synthetic-only source documents for later ingestion work. It
does not include real statements or implement parsing.

## Brokerage statement PDF (future Stage 2)

- Use a fictional institution, `Example Harbor Brokerage`, and account labels
  `[SYNTHETIC] Taxable example` / `[SYNTHETIC] Roth IRA example` only.
- Include a statement date of 2026-09-30, USD, the Stage 0 tickers SYN1, SYN2,
  SYNX and SYNB, and a separate cash balance. Quantities and prices must match
  `positions.csv`.
- Add a second page with a repeated header, a wrapped security name, and a
  clearly labelled subtotal so OCR/table extraction can be tested without
  ambiguous invented arithmetic.
- Negative cases should include one unknown ticker preserved as raw text, a
  missing price, a zero quantity, and a visibly unreadable row image. Every row
  must remain synthetic and require review before canonical publication.

## Bank / card statement PDF or CSV (future Stage 2)

- Use fictional institution `Example Harbor Bank`, holder `Synthetic Sample`,
  and no real account/routing/card identifiers.
- Use a fixed 2026-09 period, fictional merchant names, USD amounts represented
  as decimal strings, posted dates, and stable synthetic transaction IDs.
- Include a duplicate transaction, pending and reversed rows, a transfer between
  two synthetic accounts, and an ambiguous merchant category for review tests.
- Any future file should be generated from authored synthetic rows, carry a
  prominent synthetic label, and never be used to infer real ownership.

Parsers, OCR, reconciliation, transaction categories, and document upload are
future work and are intentionally absent from Stage 0.
