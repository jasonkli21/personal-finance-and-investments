# Stage 2 current release status

Updated 2026-10-03 for the GCP/Neon migration.

Stage 2 remains partial: private text-layer PDF previews, durable jobs, reviewed CSV/manual transactions, categories/splits/transfers and source-labelled balances/summaries. OCR, shared extraction, account sync, recurring-charge/month coverage, parsed-output reuse/cleanup and complete lifecycle/benchmark acceptance remain pending. The migration adapts execution infrastructure; it does not complete these features.

The exact dated implementation, methodology, test commands/counts and original limitations are preserved in [the historical release record](history/pre-gcp-neon/stage-2-release.md). Its provider deployment assumptions are superseded by [ADR 0002](adr/0002-gcp-neon.md).

Use the [current plan](stage-2-implementation-plan.md), code/OpenAPI and [migration validation](gcp-neon-migration.md) for continued development. Alembic is canonical for local PostgreSQL 16 and Neon; private cloud files use GCS. Real Neon/GCP migration, HTTPS/auth, private-object and recovery evidence remains pending. Personal AI remains disabled.
