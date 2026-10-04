"""Execution infrastructure only: Finance DB rows remain the durable queue."""

from typing import Any


def trigger_job(resource_name: str, *, client: Any | None = None) -> None:
    try:
        if client is None:
            from google.cloud.run_v2 import JobsClient

            client = JobsClient()
        # No per-execution overrides, document bytes or identifiers. A repeated
        # invocation is safe because the existing DB claim/generation fences
        # govern persistence. Never call this inside a retryable DB transaction.
        client.run_job(request={"name": resource_name}, timeout=10)
    except Exception as exc:
        raise OSError("Cloud worker invocation unavailable") from exc
