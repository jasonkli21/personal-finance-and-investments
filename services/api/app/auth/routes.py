"""OIDC login and revocable, database-backed browser sessions."""

from typing import cast

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.auth.oidc import (
    OIDC_CALLBACK_PATH,
    load_provider_metadata,
    validate_verified_identity,
)
from app.auth.service import (
    SESSION_COOKIE,
    PrincipalContext,
    create_session,
    revoke_session,
)

router = APIRouter(prefix="/v1/auth", tags=["authentication"])


class SessionRead(BaseModel):
    authenticated: bool
    local_mode: bool
    subject: str | None = None


@router.get("/session", response_model=SessionRead)
def get_session(request: Request) -> SessionRead:
    settings = request.app.state.settings
    if not settings.auth_enabled:
        return SessionRead(authenticated=True, local_mode=True)
    principal: PrincipalContext | None = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return SessionRead(authenticated=True, local_mode=False, subject=principal.subject)


@router.get("/login", include_in_schema=False)
async def login(request: Request) -> Response:
    settings = request.app.state.settings
    if not settings.auth_enabled or settings.app_public_origin is None:
        raise HTTPException(status_code=404, detail="Authentication is disabled")
    oidc_client = request.app.state.oidc_client
    if oidc_client is None:
        raise HTTPException(status_code=503, detail="Identity provider is unavailable")
    callback_url = f"{settings.app_public_origin.rstrip('/')}{OIDC_CALLBACK_PATH}"
    try:
        await load_provider_metadata(oidc_client, settings)
        return cast(
            Response, await oidc_client.authorize_redirect(request, callback_url)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Identity provider is unavailable"
        ) from exc


@router.get("/callback", include_in_schema=False)
async def callback(request: Request) -> Response:
    settings = request.app.state.settings
    if not settings.auth_enabled or settings.app_public_origin is None:
        raise HTTPException(status_code=404, detail="Authentication is disabled")
    oidc_client = request.app.state.oidc_client
    if oidc_client is None:
        raise HTTPException(status_code=503, detail="Identity provider is unavailable")
    try:
        await load_provider_metadata(oidc_client, settings)
        # Authlib checks callback state, PKCE, ID-token signature via discovered
        # JWKS, issuer, audience, expiry, and the nonce saved at login start.
        token = await oidc_client.authorize_access_token(request, leeway=0)
        claims = token.get("userinfo")
        if not isinstance(claims, dict):
            raise ValueError("The identity response has no verified ID token")
        identity = validate_verified_identity(claims, settings)
    except Exception as exc:
        raise HTTPException(
            status_code=401, detail="Identity could not be verified"
        ) from exc

    result = create_session(
        request.app.state.session_factory,
        settings,
        issuer=identity.issuer,
        subject=identity.subject,
        scope_id=settings.auth_personal_scope_id or "",
        correlation_id=request.state.correlation_id,
    )
    if result is None:
        raise HTTPException(status_code=401, detail="Identity is not authorized")
    session_token, principal = result
    response = RedirectResponse(settings.app_public_origin, status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=settings.auth_session_ttl_seconds,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="strict",
        path="/",
    )
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response) -> Response:
    settings = request.app.state.settings
    principal: PrincipalContext | None = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    revoke_session(
        request.app.state.session_factory,
        principal,
        correlation_id=request.state.correlation_id,
    )
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="strict",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
