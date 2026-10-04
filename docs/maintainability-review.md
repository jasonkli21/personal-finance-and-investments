# Current maintainability review and lineage

Updated 2026-10-03 after the GCP/Neon rearchitecture. The exact preceding repository review, fixes and observed test counts are preserved in [the historical review](history/pre-gcp-neon/maintainability-review.md). [The migration record](gcp-neon-migration.md) contains the new architecture audit and validation; prior provider-specific gates are superseded by [ADR 0002](adr/0002-gcp-neon.md).

The modular monolith, finance authority, shared quote selection, revision-bound drafts, source validation, Decimal precision, publication fences, private-file integrity, auth/session race protections and safe logging remain intact. Alembic is the sole schema path; local PostgreSQL and Neon share psycopg. GCS replaces the cloud storage implementation. Cloud Run executes the API and existing lease-fenced jobs; Firebase Hosting preserves the same-origin browser surface through explicit path/cookie transport. No product-stage completion is inferred from infrastructure work.

Remaining product findings from the preceding review still apply:

- Stage 2 OCR, shared extraction, account sync, recurring-charge/month coverage, parsed-output reuse/cleanup, complete worker restart/cancellation and benchmark acceptance remain partial/gated.
- Supplied remaining lot balances do not establish a fully dated historical lot ledger; define observation/reconciliation policy before historical extensions.
- Manual research facts do not establish structured XBRL dimension/amendment equivalence. Values remain user_supplied_unverified.
- Research lists retain hard caps without pagination/completeness contracts; frozen results still retain selected input identities/hashes.
- Personal AI transport, verified owner/service authorization, live retrieval/synthesis and monitoring remain unavailable. Provisional metadata validation is not semantic evidence authentication.
- Real Neon/GCP connection/migration/concurrency, hosted HTTPS/OIDC/private-object access, job lifecycle, cost alerts and cloud recovery remain unverified. Offline tests cannot satisfy those gates.

Run the normal aggregate quality gate and disposable PostgreSQL/browser journeys. Finish requested Stage 2 acceptance before monitoring relies on jobs. Define dated-lot and research comparison/list contracts when those domains are extended. Real-data service egress follows the ownership ADR and separately approved data-handling rules.
