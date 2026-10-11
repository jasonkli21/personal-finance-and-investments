"""Separate Google service and end-user identity checks for Finance reads."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from app.config import Settings

GOOGLE_ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})


class FinanceContextAuthorizationError(ValueError):
    """Stable rejection that does not reveal whether an owner/entity exists."""


@dataclass(frozen=True)
class VerifiedFinanceContextIdentity:
    issuer: str
    subject: str


def _bounded_google_request_type() -> Callable[[], Any]:
    from google.auth.transport.requests import Request

    class BoundedGoogleRequest(Request):
        def __call__(
            self,
            url: str,
            method: str = "GET",
            body: bytes | None = None,
            headers: Mapping[str, str] | None = None,
            timeout: int | float | None = 3,
            **kwargs: Any,
        ) -> Any:
            request = cast(Callable[..., Any], super().__call__)
            return request(
                url,
                method=method,
                body=body,
                headers=headers,
                timeout=min(timeout or 3, 3),
                **kwargs,
            )

    return cast(Callable[[], Any], BoundedGoogleRequest)


class FinanceContextIdentityVerifier:
    """Verify separate caller and user ID tokens against pinned audiences."""

    def verify(
        self,
        *,
        service_token: str,
        user_token: str,
        settings: Settings,
    ) -> VerifiedFinanceContextIdentity:
        if not settings.finance_context_read_enabled:
            raise FinanceContextAuthorizationError("finance_context_disabled")
        if (
            not service_token
            or not user_token
            or len(service_token) > 8192
            or len(user_token) > 8192
        ):
            raise FinanceContextAuthorizationError("finance_context_identity_invalid")

        service_claims = self._google_claims(
            service_token, settings.finance_context_service_audience
        )
        if (
            service_claims.get("email") != settings.finance_context_service_account
            or service_claims.get("email_verified") is not True
        ):
            raise FinanceContextAuthorizationError("finance_context_caller_denied")

        user_claims = self._google_claims(
            user_token, settings.finance_context_user_audience
        )
        subject = user_claims.get("sub")
        issuer = user_claims.get("iss")
        issued_at = user_claims.get("iat")
        if (
            issuer != settings.auth_issuer_url
            or issuer not in GOOGLE_ISSUERS
            or not isinstance(subject, str)
            or subject != settings.auth_allowed_subject
            or not isinstance(issued_at, (int, float))
            or isinstance(issued_at, bool)
            or issued_at > time.time() + 30
            or time.time() - issued_at
            > settings.finance_context_user_token_max_age_seconds
        ):
            raise FinanceContextAuthorizationError("finance_context_user_denied")
        return VerifiedFinanceContextIdentity(issuer=issuer, subject=subject)

    @staticmethod
    def _google_claims(token: str, audience: str) -> dict[str, Any]:
        try:
            from google.oauth2.id_token import verify_oauth2_token

            request = _bounded_google_request_type()()
            verify_token = cast(Callable[..., dict[str, Any]], verify_oauth2_token)
            claims = verify_token(
                token,
                request,
                audience=audience,
                clock_skew_in_seconds=30,
            )
        except Exception as error:  # Google verifier errors may carry token details.
            raise FinanceContextAuthorizationError(
                "finance_context_identity_invalid"
            ) from error
        finally:
            if "request" in locals():
                request.session.close()
        if not isinstance(claims, dict) or claims.get("iss") not in GOOGLE_ISSUERS:
            raise FinanceContextAuthorizationError("finance_context_identity_invalid")
        return claims
