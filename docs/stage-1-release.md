# Stage 1 current release status

Updated 2026-10-03 for the GCP/Neon migration.

Stage 1 local MVP remains delivered: reviewed position CSVs, generic/iShares fund CSVs and SPDR XLSX, dated manual/cached quotes, Decimal owned valuation and reconciled one-level issuer/security exposure, immutable reports/drill-down/export. Live quote/issuer retrieval remains unavailable. Original delivery commits: f75e101, 9053d1f and 0874f21.

The exact dated implementation, methodology, test commands/counts and original limitations are preserved in [the historical release record](history/pre-gcp-neon/stage-1-release.md). Its provider deployment assumptions are superseded by [ADR 0002](adr/0002-gcp-neon.md).

Use the [current plan](stage-1-implementation-plan.md), code/OpenAPI and [migration validation](gcp-neon-migration.md) for continued development. Alembic is canonical for local PostgreSQL 16 and Neon; private cloud files use GCS. Real Neon/GCP migration, HTTPS/auth, private-object and recovery evidence remains pending. Personal AI remains disabled.
