# Stage 2 implementation status

Status: in progress. The first S2.1 local text-PDF preview slice is implemented; Stage 2 is not complete. Live DSQL, private cloud access control, OCR, personal-AI transport, bank/card transaction records, finance dashboards, optional account sync, and asynchronous jobs remain unimplemented or gated.

## S2.1 local slice

`POST /v1/imports/documents/positions/preview` accepts one bounded PDF and account/date/source/revision metadata. It extracts a supported text-layer holdings table in a resource-limited child process, preserves the original PDF in the private file store, and stages normalized rows through the Stage 1 position import review. Review corrections, cancellation, and publication use the existing `/v1/imports/{id}` workflow. `GET /v1/documents/{id}` returns safe metadata and parser diagnostics; `GET /v1/files/{id}/preview` serves a linked PDF with private/no-store headers.

Supported parser layout: a single holdings table with recognized identifier/name, quantity, price/value, and optional currency columns, with cells separated by repeated spaces or pipes. Evidence uses page and line numbers. Quantity × price mismatches, absent prices/values, absent/mismatched statement dates, assumed account currency, and unparsed lines remain warnings/review rows. A PDF without an extractable text layer or with an unsupported table must use the existing CSV/manual workflow. This is not OCR and does not infer trades, cost basis, or missing identifiers.

The checked-in example is wholly synthetic: [`fixtures/stage-2/synthetic-brokerage-statement.pdf`](../fixtures/stage-2/synthetic-brokerage-statement.pdf), with [`expected-brokerage-extraction.json`](../fixtures/stage-2/expected-brokerage-extraction.json). The parser's dependency is pypdf 6.x; original files stay outside SQL and static/public assets. Private file access currently assumes the local single-user deployment boundary. Do not expose these routes in an unauthenticated hosted deployment; Stage 4 auth/storage controls are not implemented.

## Package status and gates

| Package | Status | Notes |
| --- | --- | --- |
| S2.1 files and deterministic preview | Partial | PDF preview uses existing reviewed position publication. Upload size, parser time/page/row/text bounds are configured. Correction history for PDF-specific diagnostics, document CSV adapters, worker execution, and full acceptance evidence remain. |
| S2.2 shared candidate extraction | Deferred at dependency gate | Upstream extraction transport, verified identity/owner propagation, and reviewed real-data handling are not available. `PERSONAL_AI_ENABLED=false`; no statement transmission. |
| S2.3 transactions/categories/transfers | Pending | No canonical transaction schema or workflow has shipped yet. |
| S2.4 finance/net-worth views | Pending | No spending summary or unified balance view has shipped yet. |
| S2.5 read-only account sync | Optional; evaluation only | Current official Plaid documentation requires production product access and production billing depends on product/agreement. No production tokens or connections are present. See [source evaluation](03-data-sources.md#plaid). |
| S2.6 jobs and release evaluation | Pending | PDF parse is synchronous from the user's perspective; no durable job/lease/worker contract exists. |

## Verification state

The generated OpenAPI JSON and TypeScript schema include the S2.1 routes and contracts. The Stage 2 parser, migration, preview/review, duplicate-upload, and browser journey have not been run against a database or browser for this delivery. The live DSQL path is unverified. Do not treat the synthetic expected JSON as a benchmark result.

Continue with the repo commands in [`README.md`](../README.md). After dependencies are installed, regenerate contracts with `pnpm api:generate`. Apply local schema changes through the usual Alembic migration command. Before hosted use, add authentication and authorization for document metadata and private previews, and complete the real DSQL gate.
