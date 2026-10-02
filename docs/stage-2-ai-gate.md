# S2.2 shared extraction gate

**Reviewed:** 2026-10-02
**Decision:** Do not add or enable finance-to-personal-AI transport for actual statements.

The S2.2 plan requires an agreed extraction endpoint/schema plus scoped consent, reviewed handling/retention, authenticated service access, and verified user-owner propagation. The adjacent `personal-ai-system` checkout was inspected on this date:

- Its current FastAPI route module exposes conversation routes; it does not define a generic document-extraction route or versioned extraction request/response contract.
- Its API dependency returns a fixed `local` owner. The repository README states that this surface has no authentication and is not for sensitive personal data.
- Finance's `PersonalAIClient` remains a disabled protocol seam. There is no configured HTTP adapter, URL, service credential, or path that sends source bytes/text upstream.

Therefore `PERSONAL_AI_ENABLED` stays `false`, and finance does not send actual statement content to this service. The local text-PDF parser remains deterministic and uses manual review; unsupported scans/layouts use the CSV/manual fallback. Resume S2.2 only after the upstream owners publish a versioned extraction contract and provide verified authentication/authorization, identity propagation, data-use/retention terms and scoped-consent handling. The finance adapter must then enforce the bounded transport and evidence validation in [the ingestion design](04-ingestion-and-ai.md#5-personal-ai-integration-boundary).
