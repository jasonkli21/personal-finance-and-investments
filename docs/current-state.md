# Current implementation state — Personal Finance

Updated 2026-10-14. This is the living delivery boundary. Code, contracts,
migrations and tests take precedence over plans. The stabilization patch is based
on `495c21186b68215bf110ab6ab3115cd67190cc67`; final commit/source identity and exact checks are recorded in the
[verification record](stabilization-2026-10-14.md). Independent final review and
external acceptance remain open.

## Implemented locally

Finance owns canonical portfolios, holdings, Decimal calculations, tax scenarios,
transactions, imports, monthly budgets, provenance and UI. Tax scenarios and ETF
look-through remain derived estimates; Stage2 ingestion/recurring/month-coverage
and full worker acceptance gaps remain open. Stage4 tooling is not deployed;
Stage5 live research/source authenticity gates remain open.

The disabled extraction client remains disabled. A separate, default-off typed
Shopping task now reads an explicitly shared monthly budget, validates source
and Shopping revisions, reviews and confirms a PAI proposal, applies once and
recovers the original command/confirmation identity. Source command creation
lives in the domain service; routes and generated API types expose a small status.
Migration0020 retains verified upstream authentication time without backfilling
unknown sessions;0021 persists immutable commands and refuses populated rollback.

The source now loads the linked user's active Shopping projects through the
read-only Personal AI target-choice route. The picker sends the selected project
ID and current revision; Shopping remains authoritative and rejects a stale
revision at validation or apply. Recovery stays tied to the original command,
confirmation and execution identity.

OpenAPI/client generation, session-factory typing and schema-count/recovery
expectations were corrected. The cached-quote fixture now pins valuation time;
production financial math was unchanged. Evidence-key fixtures are explicitly
synthetic and independent of environment files. Native migration/recovery and
full local package checks are recorded separately from Neon/GCP/real-data gates.
No personal Finance data was sent to a model provider.

## Verification and release boundary

Read [the local stabilization evidence](stabilization-2026-10-14.md) and
[suite verification](https://github.com/jasonkli21/personal-ai-agent/blob/main/stabilization/VERIFICATION.md).
The all-five synthetic PostgreSQL/loopback HTTPS paths do not prove real IAM,
provider, cloud, browser or native-device behavior. Feature gates remain off by
default. No cloud deployment or live-provider operation was run. The user
authorized local commits followed by pushes to each remote `main`. Hosted CI is
separate evidence.

## Minimum context

Read [the router](README.md), the owning module/contract and focused tests.
[Suite contracts](https://github.com/jasonkli21/personal-ai-agent/blob/main/stabilization/CROSS-REPO-CONTRACTS.md),
[operations](https://github.com/jasonkli21/personal-ai-agent/blob/main/stabilization/OPERATIONS.md) and the
[fresh re-review handoff](https://github.com/jasonkli21/personal-ai-agent/blob/main/stabilization/FRESH-REVIEW-HANDOFF.md) explain
cross-app assumptions and remaining acceptance. The
[previous status](history/stabilization/current-state-before-2026-10-14.md)
preserves detailed predecessor phase evidence and unresolved gates. This status
does not authorize implementation of the future roadmap.
