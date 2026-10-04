# GCP / Neon migration record — 2026-10-03

## Live baseline and scope

Audited checkout: `4e5f3e330a401a4df2f75781689a42300868bdbb`.
The only pre-existing untracked content was `finance-gcp-neon-migration-handoff/`, preserved unchanged.
Code and release evidence show Stage 0–1 delivered locally, Stage 2 partial (text PDF jobs, reviewed transactions and summaries), Stage 3 delivered locally, Stage 4 prepared deployment tooling, and Stage 5 an offline/manual research baseline. OCR, account sync, live retrieval/synthesis/monitoring and Personal AI transport/authorization remain gated.
The release records explicitly report no provisioned cloud resources; no Terraform state or live target configuration is present in this checkout. This is repository evidence, not a remote account inventory. No cutover, dual write, or real-data migration is justified.

Baseline `pnpm check` passed after putting the bundled Node executable on PATH: generated API, lint, formatting, type checks, 22 web tests, 5 infrastructure contracts, 233 backend passes / 57 credentialed or PostgreSQL-gated skips, and web build. The existing 540 kB bundle warning remains. PostgreSQL 16 validation uses a new disposable loopback cluster at port 55447; results are recorded below.

## Migration map

| Area | Classification | Decision / regression gate |
| --- | --- | --- |
| Finance domains, Decimal/NUMERIC, UUIDs, provenance, reviews, frozen reports | Preserve | Keep canonical data and calculations; run all finance workflows |
| Local PostgreSQL 16, Alembic revisions 0001–0018 | Preserve | Do not edit applied migrations; fresh and populated upgrades |
| Standard engine/pool, DB-only retries | Generalize | One psycopg path, runtime URL plus optional direct migration URL, verified TLS in production; bounded retries |
| Independent DSQL plan, ledger, dialect, IAM tokens, async indexes | Retire after parity | Compare final relational schema before deletion; retain audit findings |
| FileStore protocol and PrivateFileStore | Preserve | Same content-addressing, private previews and bounded integrity checks |
| S3 adapter | Replace | GCS with ADC, generation preconditions, bounded reads and duplicate verification |
| OIDC/PKCE, revocable DB sessions, allowed owner, CSRF/origin checks | Preserve / adapt edge | Firebase retains /api paths and forwards only __session: explicit path/cookie transport required |
| Durable job rows, cancellation and lease generation fencing | Preserve | Local polling plus bounded Cloud Run Job; external execution outside DB retries |
| AWS Terraform / helper, deployment evidence, costs | Replace | Cloud Run, Artifact Registry, private GCS, Secret Manager, service identities, Firebase configuration; no apply |
| Encrypted portable recovery | Generalize | Alembic source revision and GCS files; isolated local restores, tamper and scope checks |
| Release fingerprints, missing/skipped evidence blocking | Preserve / simplify | Neon migration/reconnect/concurrency and hosted HTTPS/private-storage/recovery gates |
| Dated releases/reviews and old compatibility contract | Historical only | Preserve exact old facts under docs/history; current docs supersede provider assumptions |
| Personal AI extraction and provisional research evidence | Preserve gated | No transport or private-data egress introduced |

## High-risk seams

Schema parity, populated backfills, same-origin callback cookies, partial job restarts, private-file integrity, archive compatibility, and source/configuration-bound promotion evidence are mandatory regression areas. Limits on rows, bytes and transaction sizes remain where they bound memory, latency, review size or repeatable publication. They no longer encode a provider transaction ceiling.

## Schema parity and validation

Pre-retirement parity replay on PostgreSQL 16.15: 45 tables on each path, zero differences in columns/types/nullability/defaults, primary keys, unique constraints, check expressions, foreign-key targets/delete actions, or indexes. The independent plan was replayed in an isolated schema after removing only ASYNC syntax; no backfill ran on that empty schema. Alembic head is `0018_stage5_portfolio_context`. Alembic 0003 implements the same manual-revision/pointer/alias backfill and the existing populated 0002 upgrade test checks its preserved history. Alembic 0011 repairs/backfills transaction descriptions omitted by 0008; the independent plan creates description at 0008. Final schemas match. Baseline PostgreSQL suite: 275 passed, 15 cloud-only skipped, including fresh install, populated upgrade and encrypted recovery. Post-rewrite validation follows below. Real Neon/GCP evidence remains pending until disposable credentials/resources are supplied. Local or mocked tests cannot pass the hosted promotion gate.

## Final architecture and validation

The active application now has one standard PostgreSQL/psycopg engine and one Alembic schema history. Runtime DATABASE_URL and optional direct MIGRATION_DATABASE_URL replace the second dialect. Production validates verified Neon TLS and authenticated HTTPS/private GCS settings. Query parameters cannot override the inspected database endpoint. Alembic also rejects missing production connection URLs and unverified URLs, including mixed-case APP_ENV values. No applied revision was changed.

GCS preserves the FileStore boundary with ADC, create-only generation conditions, duplicate byte/hash verification, bounded generation-pinned reads and stream cleanup. Local PrivateFileStore is unchanged. Firebase path handling and signed `__session` transport retain OIDC/PKCE, signed state/nonce, revocable DB sessions and exact-origin/CSRF/server authorization. Tests include direct service paths, direct-cookie rejection, tampered transport and logout revocation.

The local polling runner and Finance job rows/lease generations remain authoritative. Cloud invocation follows durable enqueue and carries no document payload or per-execution overrides. Failed client initialization or invocation leaves the job retryable; repeated upload reuses the same identity. The bounded worker shares the existing parser/retry/cancellation/publication fences. Backlog draining and interrupted enqueue/invoke remain required hosted rehearsals, not completion claims for Stage 2.

Prepared Terraform replaces the predecessor infrastructure with private/versioned GCS, API/worker identities, three Secret Manager containers with pinned external versions, Artifact Registry, bounded Cloud Run API/Job and Firebase Hosting configuration. No credential payload or service-account key enters Terraform. Bootstrap excludes runtime until an immutable image is provided. Object deletion/policy privileges are withheld; destructive cleanup is protected. Default log retention and request-URL exclusions are configured, with other sinks explicitly requiring review. Optional project-number-bound billing alerts are not spending caps; Neon costs remain separate.

Encrypted recovery retains authenticated encryption, referenced object hash/length checks, owner-scope validation, bounded resumable staging, isolated loopback restore, tamper detection and session omission. Sources/archives now identify the canonical Alembic head; retired ledger archives are not accepted. There is no evidence of provisioned predecessor data to cut over. Existing PostgreSQL archive format remains version 1.

| Validation | Result |
| --- | --- |
| `pnpm check` with disposable PostgreSQL 16 and isolated recovery admin URL | Passed: 273 backend tests, 22 web tests, 6 infrastructure guardrails; generated API, lint/format, strict types and web build. 11 skips = 9 explicit Neon gates + 2 SQLite concurrency variants whose PostgreSQL counterparts pass |
| PostgreSQL schema parity before retirement | 45 tables each; zero structural differences; populated 0002 backfill and 0010 transaction-description upgrade preserve history/source values |
| Real PostgreSQL conflict/concurrency | Actual serialization conflict retries in a fresh transaction without lost update; Stage 1 publication and Stage 2 revision CAS counterparts pass (2 focused passes; their SQLite variants intentionally skip) |
| `pnpm test:e2e` with distinct disposable PostgreSQL database | 7 passed: offline portfolio/review journeys and current regression paths |
| Terraform 1.14.7 `fmt -check`, `validate`, `test` | Provider-schema validation passed; 2 mocked bootstrap/runtime plans passed; no resources applied. Locked Google providers 7.46.1 include Mac ARM64 and Linux AMD64 checksums |
| Neon evidence CLI without explicit target opt-in | Blocks with exit 2; no passed cloud artifact emitted |
| API package / container | `uv build --offline` passed: source distribution and wheel. Docker executable/runtime unavailable, so container build pending |

No disposable Neon/GCP configuration or callable cloud CLI is available. Real Neon migration/populated-upgrade/reconnect/concurrency, HTTPS edge and direct-service auth, private GCS denial/preview, Cloud Run worker execution, log privacy, cost alerts and encrypted cloud-to-local recovery remain **pending**. No resource provisioning, deployment, real-data transfer or Personal AI call occurred. Release evidence cannot promote local/mocked results to hosted readiness; committed source, immutable image, independently bound target/configuration artifacts and reviewed approval remain required.

Stage 2 remains partial, Stage 3 remains locally delivered, and Stage 5 remains offline/manual. OCR, institution coverage, parsed-output reuse/cleanup, account sync, research semantic/authenticity/list-completeness contracts, live retrieval/synthesis and monitoring are unchanged. PERSONAL_AI_ENABLED=true remains rejected.

The final repository-wide provider-reference audit classifies remaining matches as exact historical snapshots under docs/history/pre-gcp-neon, explicitly historical demo/evaluation records, the old compatibility pointer, migration/ADR/handoff commentary, or the immutable 0011 migration comment. Stage IDs, secret variable names and dependency integrity hashes are unrelated substring matches. No predecessor provider remains in active application, infrastructure or current deployment instructions. Current docs, plans and release gates present one coherent GCP/Neon target; hosted readiness is explicitly unverified.
