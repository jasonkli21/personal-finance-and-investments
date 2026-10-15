# Personal Finance stabilization evidence — 2026-10-14

Base revision: `495c21186b68215bf110ab6ab3115cd67190cc67`. This record covers the committed stabilization patch,
including earlier Luna changes reconciled by direct implementation QA. Independent
final review is intentionally owned by a separate session.

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

OpenAPI/client generation, session-factory typing and schema-count/recovery
expectations were corrected. The cached-quote fixture now pins valuation time;
production financial math was unchanged. Evidence-key fixtures are explicitly
synthetic and independent of environment files. Native migration/recovery and
full local package checks are recorded separately from Neon/GCP/real-data gates.
No personal Finance data was sent to a model provider.

Fresh browser CI exposed the fixed October 1 manual-price fixture being valued
after its seven-day freshness window. The journey now explicitly selects a
historical valuation on the fixture date, retaining every NAV, percentage,
breakdown, CSV and reload assertion. Production financial/freshness rules remain
unchanged.

## Evidence authority

[Exact commands/counts/source identity](https://github.com/jasonkli21/personal-ai-agent/blob/main/stabilization/VERIFICATION.md),
[fresh re-review handoff](https://github.com/jasonkli21/personal-ai-agent/blob/main/stabilization/FRESH-REVIEW-HANDOFF.md)
is the suite evidence index. Earlier records retain their original date/results;
newer local evidence supersedes their unrun-local-check statements only.

No personal records were used or deleted. Local tests created disposable databases
and synthetic private-store directories. Root-owned test processes are stopped at
handoff. Credentials, private payloads and unrelated user files are excluded from
commits. Cloud/provider/device/hosted CI acceptance cannot be inferred from this
local patch, and erasure does not independently invalidate previously downloaded
exports or historical cloud backups.
