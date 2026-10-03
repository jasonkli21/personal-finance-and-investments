# Stage 5 offline evaluation report

**Evaluation date:** 2026-10-03
**Suite:** `stage5-offline-evaluation-v1`
**Fixture:** [`fixtures/stage-5/synthetic-research-evaluation.json`](../fixtures/stage-5/synthetic-research-evaluation.json)

## Scope and reproducibility

This is a deterministic, synthetic-only evaluation of Finance's offline research baseline. It uses invented company values and non-resolving SEC-shaped references; it does not fetch SEC/IR content, call a model or shared research service, or use personal financial data. Run it with:

```sh
UV_CACHE_DIR=/private/tmp/codex-finance-stage5-uv-cache uv run --directory services/api --locked pytest -q tests/test_stage5_research.py tests/test_stage5_evidence.py
```

The test checks an exact Decimal comparison, run behavior with a hostile user-authored thesis note, identity binding between selected facts and registered source references, the provisional evidence-scope DTO's fields, and unchanged canonical account/position/transaction rows. S5.4 synthetic validator cases separately exercise stale, mismatched, conflicting, insufficient, untraceable, and oversized candidates. The DTO is constructed locally in the test and is never transmitted.

## Results and limits

| Evaluation dimension | Offline result | What this establishes |
| --- | --- | --- |
| Period/unit calculation | FY2024 `$100,000,000` to FY2025 `$120,000,000`; `$20,000,000` change and `20%` | Deterministic comparison uses the expected values for the fixture. |
| Citation identity | Both citations resolve to the selected fact, registered document, accession, URL, and `user_supplied_unverified` status | Finance links result records to registered user-entered references. It does not establish that a URL resolves or that the source supports the value. |
| Quotation and semantic support | Not evaluated | The offline result contains no generated factual claims or quotations. A citation link alone is not evidence of claim support. |
| Hostile thesis / unsupported instruction | Note remains labelled user thesis; the deterministic result emits no inferences and does not use the note as a citation | The disabled deterministic path does not synthesize from this instruction. This is not a prompt-injection evaluation of an LLM. |
| Staleness, attribution, conflict, size | Covered by S5.4 synthetic validator cases | The provisional validator enforces its local metadata, scope, freshness, and byte/count rules. It does not independently fetch or authenticate source content. |
| Private-context boundary | The prospective eligibility shape contains issuer, manually registered source references, as-of time, and bounded limits; it contains no portfolio amounts, account identifiers, or thesis note | This local DTO shape is narrow. No upstream request/egress path exists, so transport privacy and service authorization remain untested. |
| Disabled behavior / canonical writes | Offline run succeeds with `DisabledPersonalAIClient`; account, position snapshot, and transaction row counts are unchanged | The research baseline works without model/search and does not mutate these canonical records in this journey. This is not by itself proof of whole-app parity. |

## Unverified release evidence

- No public-company corpus or accessible-source check was run. Fixture identifiers/URLs are intentionally synthetic and were not fetched.
- No quote-level or semantic-support review ran because the upstream research/synthesis contract and authorization are not established, and the offline path generates no claims.
- Finance and `personal-ai-system` results could not be compared; the current upstream session/SSE API does not define the issuer/evidence/owner contract needed by Finance.
- No shared-service outage, timeout, quota, malformed model output, or provider-call idempotency evaluation ran; Finance makes no such request in this path.
- No browser end-to-end company-to-cited-report journey, local PostgreSQL persistence run, or real Aurora DSQL run was performed. Live PostgreSQL/DSQL behavior remains unverified; hosted promotion remains gated.
- The default app context contains the disabled AI client. This evaluation does not grant authorization for real-data calls or private-context transmission.

Accordingly, S5.6 is an offline evaluation slice, not a claim of research accuracy or a Stage 5/hosted release pass.

## Run verification

- Focused research/evidence/DSQL-structure command above: **22 passed**.
- Full API suite, `UV_CACHE_DIR=/private/tmp/codex-finance-stage5-uv-cache uv run --directory services/api --locked pytest -q -rs`: **195 passed, 37 skipped**. PostgreSQL persistence/recovery tests were skipped without a disposable PostgreSQL URL; real Aurora DSQL tests require explicit opt-in and a disposable cluster. One Alembic deprecation warning about missing `path_separator` remains.
- Frontend tests: **9 passed** across 4 files. Web TypeScript typecheck, generated API check, and production build passed. Build reports the existing 536 kB minified JavaScript chunk advisory.
- Python `mypy app tests` and full `ruff check .` passed. Ruff formatting passed for all changed Python files. Full-tree Ruff format check still reports pre-existing formatting differences in applied migrations `0007_stage2_document_ingestion.py` and `0015_stage4_authentication.py`; applied migrations were left unchanged.
- Web ESLint remains red on four existing `react-hooks/set-state-in-effect` findings in `FinanceWorkspace.tsx`, `SpendingWorkspace.tsx`, and `StageOneWorkspace.tsx`; no Stage 5 research UI file is implicated. Those findings were not changed as part of the evaluation slice.
