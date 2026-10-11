# Personal AI Finance context read contract v1

Updated 2026-10-11. This Finance-owned contract is separate from the extraction-candidate interface in `services/api/app/integrations/personal_ai.py`.

## Boundary

`POST /v1/integrations/personal-ai/context` returns a minimal, read-only projection from Finance's canonical database. The endpoint is registered only when `FINANCE_CONTEXT_READ_ENABLED=true`, which defaults to false. Finance remains authoritative for account, position, security, research, calculations, validation, private originals, and all writes. The contract has no transaction, trade, order, import, acceptance, publication, memory, or mutation method.

Personal AI owns the matching typed client/provider adapter and submits exact entity references and field names through its existing shared context planner, provider coordinator, policy, assembler, and permission revalidator. The Finance wire DTO contains no owner or workspace authority. The API resolves the authenticated user to an active `AuthPrincipal` and the configured Finance personal scope before projection. No Finance database, object store, or internal Python package is shared with Personal AI.

## Operations and bounds

The request schema is `finance-context-read-v1` and supports `current` and `verify` operations. References are UUID entity IDs, except the explicit portfolio sentinel `portfolio:all_active`. A body-supplied owner, unknown field, duplicate field/reference, extra DTO property, or mismatched entity/field scope is rejected.

- Up to 16 entity references and 16 unique fields per request.
- Up to 32 records and 32,768 response bytes, with the caller selecting smaller limits as needed.
- Request body maximum 8,192 bytes.
- Responses are `Cache-Control: no-store`.
- PostgreSQL reads use a read-only transaction and 1,800 ms statement timeout.
- The Personal AI HTTP client uses HTTPS only, no ambient proxy, no redirects, no retries, bounded response reads, and a caller deadline.

Account/security selections are exact and narrow. Position context requires the selected account and security references together. Broader portfolio context requires the explicit `portfolio:all_active` sentinel and `include_broader_context=true`; verify never accepts broad scope. The broad position projection reads only each active account's current accepted snapshot. Historical snapshots, transaction rows, tax lots, raw documents, paths, storage URLs, and source URLs are not projected.

## Projection semantics

Each record includes a stable source ID, SHA-256 source version/fingerprint, authority, source class, observed/effective time, restricted sensitivity, source references, field sensitivity, and a permission dependency. Each nested value is typed with its semantic class (`observed`, `calculated`, `assumed`, or `ai_interpreted`), known/unknown/conflict state, units, currency, as-of value, source identity/version, evidence references, quality, uncertainty, authority, and sensitivity.

Finance account/current portfolio truth uses `domain_current`. A user-authored research thesis is returned as user-asserted context. Registered external research facts use a separate `external_research` source class. They are not reclassified as canonical portfolio truth or Personal AI memory. Permission revalidation performs a fresh `verify` read and fails closed when the selected entity is absent, inactive, superseded, or its version changed.

## Identity and activation

The endpoint checks two Google ID tokens against distinct configured audiences: the exact calling service-account email and the configured end-user subject. It binds the user token issuer/subject to an active Finance principal and the configured personal scope; the request body cannot select the owner. When enabled, configuration requires Finance authentication and a pinned service audience/account plus user audience. The Personal AI adapter independently defaults off and requires Google OIDC, HTTPS, a service audience, and a service account.

Identity verifier, principal binding, default-off behavior, bounds, and projections have local synthetic tests. They do not establish deployed Google identity issuance, IAM/private invocation, production owner mapping, provider privacy/retention eligibility, browser sidecar integration, or real-data readiness. Keep both gates off until those external controls are independently accepted. The existing `PERSONAL_AI_ENABLED` extraction gate remains off and unchanged.

## Status

The Phase 28 implementation evidence is maintained in the Personal AI repository at [`phase-28-implementation-evidence.md`](../../personal-ai-system/docs/personal-ai-chapter-2/phase-28-implementation-evidence.md) when both repositories are checked out in the documented sibling layout. Sidecar hosting remains deferred until an accepted embed contract and its Phase 15/21 prerequisites exist.
