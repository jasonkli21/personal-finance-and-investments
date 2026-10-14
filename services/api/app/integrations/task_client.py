"""Bounded task-control transport behind the Finance Personal AI boundary."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import httpx2 as httpx
from google.oauth2 import id_token

from app.integrations.finance_context_auth import (
    FinanceContextIdentityVerifier,
    _bounded_google_request_type,
)
from app.integrations.task_control import (
    SourceTaskControlClient,
)
from app.integrations.task_control import (
    TaskControlRejected as TaskControlRejected,
)
from app.integrations.task_control import (
    TaskControlUnavailable as TaskControlUnavailable,
)
from app.integrations.task_settings import TaskSettings


def _service_token(audience: str, service_account: str) -> str:
    request = _bounded_google_request_type()()
    try:
        token = cast(Callable[..., str], id_token.fetch_id_token)(request, audience)
    finally:
        request.session.close()
    claims = FinanceContextIdentityVerifier._google_claims(token, audience)
    if (
        claims.get("email") != service_account
        or claims.get("email_verified") is not True
    ):
        raise TaskControlUnavailable
    return str(token)


class TaskControlClient(SourceTaskControlClient):
    """Supply Finance identity to the shared task transport."""

    def __init__(
        self,
        settings: TaskSettings,
        *,
        transport: Any = None,
        token_fetcher: Any = _service_token,
    ):
        super().__init__(
            application_id="finance",
            base_url=settings.base_url,
            audience=settings.audience,
            issuer=settings.issuer,
            key_id=settings.key_id,
            private_key=settings.private_key.get_secret_value(),
            service_account=settings.service_account,
            token_fetcher=token_fetcher,
            transport=transport,
            client_type=httpx.Client,
        )
