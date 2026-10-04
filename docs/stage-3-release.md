# Stage 3 current release status

Updated 2026-10-03 for the GCP/Neon migration.

Stage 3 remains delivered locally: source-backed investment events/history, estimated Dietz/XIRR performance, supplied tax-lot review/adjustments, read-only hypothetical sale/allocation and liquidity planning. Supplied remaining lot balances do not establish a complete dated historical ledger; missing dates/basis and qualified tax warnings remain explicit.

The exact dated implementation, methodology, test commands/counts and original limitations are preserved in [the historical release record](history/pre-gcp-neon/stage-3-release.md). Its provider deployment assumptions are superseded by [ADR 0002](adr/0002-gcp-neon.md).

Use the [current plan](stage-3-implementation-plan.md), code/OpenAPI and [migration validation](gcp-neon-migration.md) for continued development. Alembic is canonical for local PostgreSQL 16 and Neon; private cloud files use GCS. Real Neon/GCP migration, HTTPS/auth, private-object and recovery evidence remains pending. Personal AI remains disabled.
