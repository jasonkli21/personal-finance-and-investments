# Stage 4 current release status

Updated 2026-10-03. GCP/Neon deployment tooling is prepared, not provisioned or production-verified.

Implemented target: one PostgreSQL/psycopg and Alembic path; runtime and optional direct migration URLs; fail-closed Neon TLS, HTTPS OIDC and private GCS config; local/GCS FileStore; Firebase /api path and __session cookie transport; durable Finance job fencing with bounded Cloud Run Job execution; GCP Terraform and Firebase config output; immutable release fingerprints and real-Neon evidence; encrypted portable Neon/GCS export and isolated local PostgreSQL restore.

The local baseline and rewrite validation are recorded in [the migration record](gcp-neon-migration.md). No Terraform apply, Hosting deployment, Neon branch or GCS resource was created. Real Neon reconnect/concurrency/migrations, Firebase/Cloud Run HTTPS/OIDC, anonymous GCS denial/authenticated preview, worker lifecycle, cost alerts and cloud recovery remain pending. The release gate fails closed without these artifacts and explicit operator approval.

The exact original dated Stage 4 implementation/evidence is preserved in [the historical release](history/pre-gcp-neon/stage-4-release.md); its provider architecture is superseded. Stage 2 stays partial and Stage 5 stays offline/manual; Personal AI transport remains disabled. See the [current plan](stage-4-implementation-plan.md), [operations](stage-4-operations-runbook.md) and [ADR 0002](adr/0002-gcp-neon.md).
