# Personal Finance & Portfolio Intelligence — Docs

This is the stable context router and document index. For the concise implementation boundary, authorized scope, and open gates, see [current state](current-state.md). For human-facing product behavior, setup, and commands, see the [root README](../README.md).

## Authority and precedence

When sources disagree, use this order:

1. **Code, OpenAPI/contracts, migrations, and tests** describe current delivered behavior.
2. **Release, review, and verification evidence** records what was exercised. Local delivery, prepared tooling, and hosted deployment are distinct claims.
3. **Accepted ADRs** preserve durable decisions and supersession history.
4. **Product and architecture documents** define intended scope and boundaries; the source policy governs verified external facts.
5. **Roadmap and implementation plans** define sequencing and acceptance, not delivery evidence or implicit authorization.
6. **History** provides predecessor context only.

Security and privacy rules override convenience. A current user request may authorize scoped work outside the roadmap, but it does not change what earlier evidence proves. Archived test counts describe their original runs.

## Task routing

### Portfolio and UI

Start with [product scope](01-product-spec.md), [architecture](02-architecture.md), and relevant release evidence. Add source policy for provider behavior or the database contract for schema/API changes.

### Persistence and migrations

Start with [architecture](02-architecture.md) and the [PostgreSQL/Neon contract](07-postgres-neon.md). Add the migration record and relevant release evidence; read security/deployment guidance only for cloud-specific changes.

### Sources and imports

Start with the [source policy](03-data-sources.md) and [ingestion/AI design](04-ingestion-and-ai.md). Add the relevant stage plan/release, and the PostgreSQL contract for persistence or jobs.

### Personal AI

Start with [ingestion/AI](04-ingestion-and-ai.md) and the [shared AI ADR](adr/0001-shared-personal-ai.md). Read the [Stage 2 gate](stage-2-ai-gate.md) or Stage 5 plan/evidence only for the capability being changed.

### Security and deployment

Start with [security/deployment](06-security-and-deployment.md) and [ADR 0002](adr/0002-gcp-neon.md). Add the PostgreSQL contract, migration record, and Stage 4 plan/evidence as applicable.

### Stage work and research

Start with the [roadmap](05-roadmap.md), the exact stage plan, and its release/review evidence. For research or external financial facts, also read the [source policy](03-data-sources.md); add AI/auth policy only for integration or egress work.

### History

Use the [history index](history/pre-gcp-neon/README.md) only to resolve an explicit predecessor or migration question.

A small UI/domain change normally needs only the relevant product/architecture section and nearby code/evidence. Do not load every source, deployment, database, or phase document by default. Do not use history for ordinary current work.

## Current and reference documents

| Document | Role |
| --- | --- |
| [AGENTS.md](../AGENTS.md) | Durable implementation and finance safeguards |
| [Current state](current-state.md) | Single concise summary of delivery boundaries, next-scope guidance, and hard gates |
| [Product](01-product-spec.md) | Scope, user journeys, requirements, and non-goals |
| [Architecture](02-architecture.md) | Boundaries, schema, APIs, and current repository layout |
| [Sources](03-data-sources.md) | Provenance, freshness, licensing, and dated external facts |
| [Ingestion/AI](04-ingestion-and-ai.md) | Deterministic parsing, review, publication, and AI safeguards |
| [Roadmap](05-roadmap.md) | Dependency order, work packages, and acceptance criteria |
| [Security/deployment](06-security-and-deployment.md) | Auth, privacy, costs, portability, and cloud gates |
| [PostgreSQL/Neon contract](07-postgres-neon.md) | Migrations, TLS, retries, concurrency, and database evidence |
| [Shared AI ownership](adr/0001-shared-personal-ai.md) | Finance authority and separately gated upstream capabilities |
| [GCP/Neon decision](adr/0002-gcp-neon.md) | Current deployment and database decision |
| [Migration record](gcp-neon-migration.md) | Dated baseline, schema parity, migration map, and validation evidence |
| [Maintainability review](maintainability-review.md) | Latest repository review and remaining findings |

The old [Aurora DSQL contract](07-aurora-dsql-compatibility.md) is a supersession pointer, not a current database contract.

## Stage plans and evidence

Open only the plan and evidence for the stage being changed. Plans do not establish completion.

| Stage | Plan | Release/review evidence |
| --- | --- | --- |
| 0 — Foundation | [Plan](stage-0-implementation-plan.md) | [Historical demo transcript](stage-0-demo-transcript.md), [migration validation](gcp-neon-migration.md) |
| 1 — Portfolio/exposure | [Plan](stage-1-implementation-plan.md) | [Local release](stage-1-release.md) |
| 2 — Ingestion/finance/jobs | [Plan](stage-2-implementation-plan.md) | [Partial release](stage-2-release.md), [AI gate](stage-2-ai-gate.md) |
| 3 — History/lots/planning | [Plan](stage-3-implementation-plan.md) | [Local release](stage-3-release.md) |
| 4 — GCP/Neon | [Plan](stage-4-implementation-plan.md) | [Release](stage-4-release.md), [cost register](stage-4-cost-register.md), [recovery](stage-4-recovery-runbook.md), [operations](stage-4-operations-runbook.md) |
| 5 — Research | [Plan](stage-5-implementation-plan.md) | [Release](stage-5-release.md), [evaluation](stage-5-evaluation.md) |

## History

[Pre-GCP/Neon documentation](history/pre-gcp-neon/README.md) preserves superseded provider assumptions and dated evidence; it is not current guidance. The one-time [GCP/Neon migration handoff](history/gcp-neon-migration-handoff/README.md) is archived planning context; use ADR 0002 and the migration record for current decisions and evidence.
