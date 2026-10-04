# ADR 0002 — GCP runtime and one PostgreSQL contract

Accepted: 2026-10-03. Supersedes the AWS/Aurora DSQL deployment portions of earlier documents, including ADR 0001; its Finance/Personal AI ownership decision remains in force.

Keep PostgreSQL 16 locally and use ordinary Neon PostgreSQL in cloud through SQLAlchemy 2 / psycopg 3. Alembic is the sole schema history. DATABASE_URL serves runtime traffic; optional MIGRATION_DATABASE_URL selects a direct endpoint / migration identity. Use verified TLS, small pools, pre-ping and bounded database-only retries. Preserve UUIDs, Decimal, source provenance, staged review, atomic publication and lease fencing.

Deploy the single FastAPI backend to Cloud Run; store private originals/artifacts in GCS behind FileStore using ADC from a dedicated service identity. Artifact Registry holds immutable images. Secret Manager holds database and OIDC secrets. Firebase Hosting serves the SPA and forwards /api/** to Cloud Run; the backend strips that prefix before routing and transports OIDC state and the existing revocable session through Firebase's sole forwarded __session cookie. Identity remains provider-neutral OIDC/PKCE. Backend authorization applies at both edge and direct service URLs.

Finance job rows remain durable application state. A bounded Cloud Run Job executes the existing worker; duplicate invocations compete through the current DB lease fence. No new queue or product state machine. Personal AI remains disabled pending a separately agreed transport, service/user authorization and data-handling review.

Local and cloud databases are independent. No provisioned predecessor deployment is evidenced in the checkout. Infrastructure preparation is not deployment evidence. Promotion requires real disposable Neon migration, reconnect/concurrency, hosted auth/private-object and encrypted recovery evidence. Dated predecessor release facts remain in docs/history.
