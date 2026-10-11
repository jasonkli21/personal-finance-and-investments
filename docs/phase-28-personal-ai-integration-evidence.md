# Phase 28 Finance integration evidence

**Date:** 2026-10-11
**Status:** Local read-only contract implemented; Phase 28 remains incomplete.
**Tested revision:** Worktree based on Finance `7b34529e2f9a9667558cfa6c04cd1a8af96ed8b1`.

## Boundary and ownership

Finance owns `finance-context-read-v1` at `POST /v1/integrations/personal-ai/context`. The separately versioned contract returns selected account, balance, security, current position, user-authored thesis, and registered research-fact projections. It does not widen or reuse `PersonalAIClient.extract`, which remains an independent disabled candidate-extraction seam.

Finance remains the canonical owner of accounts, accepted snapshots, securities, calculations, research records, provenance, and private originals. The contract is read-only and does not expose transactions, tax lots, raw statement bodies, file paths, storage URLs, publication, or mutation operations. Portfolio expansion requires the explicit `portfolio:all_active` reference and `include_broader_context=true`. The API maps verified identity to the active configured Finance principal before querying; the request body contains no owner or scope authority.

Values retain semantic class, state, unit/currency, as-of time, source identity/version, evidence references, quality/uncertainty, authority, and restricted sensitivity. Account balance absence remains unknown, registered external research remains distinct from current domain truth, and source-version checks fingerprint the projected position values as well as their accepted snapshot dependencies.

## Verification

Checks were run against the Phase 28 worktree using synthetic fixtures and local tooling:

- `tests/test_finance_context.py`: **9 passed**.
- Full API suite: **237 passed, 55 skipped, 1 failed**. The failure is `test_cached_quote_asof_precedence_and_signed_percentages` in the existing portfolio valuation tests. It fails in isolation on both the Phase 28 worktree and an archive of the untouched baseline revision above (`total_usd` is `None` instead of the expected value), so it predates this integration.
- Infrastructure contract test: **6 passed**.
- Ruff whole-tree lint and format checks: passed.
- Mypy over `app`, `tests`, and shared tests: **113 files, no issues**.
- Web lint, typecheck, format check, and tests: passed; **8 test files, 22 tests passed**.
- Web production build: passed. Vite reported a large-chunk warning for the 540.52 kB JavaScript bundle.
- Direct OpenAPI export and TypeScript generation matched the committed `apps/web/src/api/openapi.json` and `schema.d.ts` byte-for-byte.

The aggregate `pnpm check` was rerun with `UV_NO_SYNC=1` and a temporary uv cache so the checked-in API environment could be used without resolving build dependencies. Its API contract check, lint, format, typecheck, web tests, and infrastructure contract all passed; the command then stopped on the same baseline API test failure above. The web production build passed separately. An API package build remains unverified because `hatchling` is not cached and network DNS is unavailable.

## Deployment and remaining gates

The read endpoint is omitted from default OpenAPI and is not registered unless `FINANCE_CONTEXT_READ_ENABLED=true`; configuration validation requires explicit Google caller/user identity settings. Finance and Personal AI remain default-off. Synthetic tests cover separate service/user audiences, pinned user subject, active-principal binding, body/result bounds, no-store responses, read-only transaction behavior, wrong-principal denial, provenance, unknown/conflict states, and source-version revalidation.

Real Google token issuance, IAM/private service invocation, deployed owner mapping, database read-only behavior on the deployed PostgreSQL service, model/provider data-use and retention eligibility, and cloud recovery remain unverified. Keep the gate off until those controls are accepted. No private Finance data was sent to an external provider during verification.

The Phase 28 sidecar is deferred because Finance has no accepted embed/host contract for the current frontend. The required Phase 15 source-revocation and Phase 21 workflow-routing prerequisites also remain open. No parallel embed mechanism or domain action path was added; Copy/save-as-draft/research-note integration remains unavailable. These are material plan gaps, so this evidence does not mark Phase 28 complete.
