# Stage 2 implementation status

Status: in progress. Local S2.1 text-PDF preview, S2.3 transaction review, S2.4 summary/balance views, and S2.6 PDF jobs are partial; Stage 2 is not complete. Live DSQL, private cloud access control, OCR, personal-AI transport, optional account sync, and release evaluation remain unimplemented or gated.

## S2.1 local slice

`POST /v1/imports/documents/positions/preview` accepts one bounded PDF and account/date/source/revision metadata, stores the original privately, and returns a durable job. The local in-process worker extracts a supported text-layer holdings table in a resource-limited child process and stages normalized rows through the Stage 1 position import review. `GET /v1/jobs/{id}` exposes safe progress/result state; `POST /v1/jobs/{id}/cancel` cancels pending work or requests cancellation before review publication. The browser preserves the active job ID across reloads. Review corrections, cancellation, and publication use the existing `/v1/imports/{id}` workflow. `GET /v1/documents/{id}` returns safe metadata and parser diagnostics; `GET /v1/files/{id}/preview` serves a linked PDF with private/no-store headers.

Supported parser layout: a single holdings table with recognized identifier/name, quantity, price/value, and optional currency columns, with cells separated by repeated spaces or pipes. Evidence uses page and line numbers. Quantity × price mismatches, absent prices/values, absent/mismatched statement dates, assumed account currency, and unparsed lines remain warnings/review rows. A PDF without an extractable text layer or with an unsupported table must use the existing CSV/manual workflow. This is not OCR and does not infer trades, cost basis, or missing identifiers.

The checked-in example is wholly synthetic: [`fixtures/stage-2/synthetic-brokerage-statement.pdf`](../fixtures/stage-2/synthetic-brokerage-statement.pdf), with [`expected-brokerage-extraction.json`](../fixtures/stage-2/expected-brokerage-extraction.json). The parser's dependency is pypdf 6.x; original files stay outside SQL and static/public assets. Private file access currently assumes the local single-user deployment boundary. Do not expose these routes in an unauthenticated hosted deployment; Stage 4 auth/storage controls are not implemented.

Local job defaults are `JOB_WORKER_ENABLED=true`, `JOB_POLL_INTERVAL_SECONDS=1`, `JOB_LEASE_SECONDS=30`, and `JOB_MAX_ATTEMPTS=3`. The lease must exceed `PDF_PARSER_TIMEOUT_SECONDS`; retries use a capped exponential delay. Disable the worker only when the PDF preview route should reject requests.

## Package status and gates

| Package | Status | Notes |
| --- | --- | --- |
| S2.1 files and deterministic preview | Partial | PDF preview uses existing reviewed position publication and now runs through the local durable worker. Upload size, parser time/page/row/text bounds are configured. Correction history for PDF-specific diagnostics, document CSV adapters, and full acceptance evidence remain. |
| S2.2 shared candidate extraction | Deferred at dependency gate | Upstream extraction transport, verified identity/owner propagation, and reviewed real-data handling are not available. [`S2.2 gate evidence`](stage-2-ai-gate.md). `PERSONAL_AI_ENABLED=false`; no statement transmission. |
| S2.3 transactions/categories/transfers | Partial | Reviewed CSV/manual transactions, identity decisions, exact merchant rules, auditable categories, signed splits, and confirmed exact-match transfer link/unlink are implemented. Database/browser acceptance and live DSQL verification remain. |
| S2.4 finance/net-worth views | Partial | Posted-date cash flow, signed category/split totals, source-labelled dated balances, and net worth by currency are implemented. Balances are excluded when positions represent that account. Database/browser acceptance and live DSQL verification remain. |
| S2.5 read-only account sync | Optional; evaluation only | Current official Plaid documentation requires production product access and production billing depends on product/agreement. No production tokens or connections are present. See [source evaluation](03-data-sources.md#plaid). |
| S2.6 jobs and release evaluation | Partial | PDF preview has a durable local job, conditional lease-generation fencing, retry/status/cancel routes, and reload-persistent progress UI. Transaction CSV remains synchronous; parsed output reuse, cleanup, worker restart/cancellation acceptance, benchmark, and live DSQL checks remain. |

## Verification state

The generated OpenAPI JSON and TypeScript schema include the S2.1, S2.3, S2.4, and S2.6 routes and contracts. Static Python checks, mypy, the web TypeScript checker, and the ten-step DSQL plan structural validator passed. The Stage 2 parser, migrations, CSV review/publication, split reconciliation, transfer unlink, balance revision/net-worth reconciliation, job retry/cancel/restart, duplicate-upload, and browser journeys have not been run against a database or browser for this delivery. Offline PostgreSQL migration rendering also stops at the existing revision 0003 because its data-reconciliation step requires a live connection. The live DSQL path is unverified. Do not treat the synthetic expected JSON as a benchmark result.

Continue with the repo commands in [`README.md`](../README.md). After dependencies are installed, regenerate contracts with `pnpm api:generate`. Apply local schema changes through the usual Alembic migration command. Before hosted use, add authentication and authorization for document metadata and private previews, and complete the real DSQL gate.
