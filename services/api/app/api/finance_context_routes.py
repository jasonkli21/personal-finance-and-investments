"""Versioned Finance-owned read endpoint for Personal AI context."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.db.models import AuthPrincipal
from app.domains.finance_context import (
    FinanceContextNotFound,
    FinanceContextSelectionError,
    read_finance_context,
)
from app.integrations.finance_context import (
    FINANCE_CONTEXT_PATH,
    FinanceContextReadRequest,
    FinanceContextReadResponse,
)
from app.integrations.finance_context_auth import (
    FinanceContextAuthorizationError,
    FinanceContextIdentityVerifier,
)

router = APIRouter(tags=["Personal AI Finance context"])
MAX_REQUEST_BYTES = 8_192


async def _read_bounded_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdecimal() and int(declared) > MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="Request is too large")
    body = bytearray()
    async for block in request.stream():
        if len(body) + len(block) > MAX_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="Request is too large")
        body.extend(block)
    return bytes(body)


@router.post(FINANCE_CONTEXT_PATH, response_model=FinanceContextReadResponse)
async def read_personal_ai_context(request: Request) -> Response:
    settings = request.app.state.settings
    if not settings.finance_context_read_enabled:
        raise HTTPException(status_code=404, detail="Not found")

    authorization = request.headers.getlist("authorization")
    user_tokens = request.headers.getlist("x-user-id-token")
    if len(authorization) != 1 or len(user_tokens) != 1:
        raise HTTPException(status_code=401, detail="Authentication required")
    scheme, separator, service_token = authorization[0].partition(" ")
    if scheme.casefold() != "bearer" or not separator or not service_token.strip():
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        raw = await _read_bounded_body(request)
        body = FinanceContextReadRequest.model_validate_json(raw)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=422, detail="Invalid Finance context request"
        ) from error

    verifier = getattr(
        request.app.state,
        "finance_context_identity_verifier",
        FinanceContextIdentityVerifier(),
    )
    try:
        identity = await run_in_threadpool(
            verifier.verify,
            service_token=service_token.strip(),
            user_token=user_tokens[0],
            settings=settings,
        )
    except FinanceContextAuthorizationError as error:
        raise HTTPException(
            status_code=401, detail="Authentication required"
        ) from error

    session_factory = request.app.state.session_factory
    try:
        with session_factory() as session:
            with session.begin():
                if session.get_bind().dialect.name == "postgresql":
                    session.execute(text("SET TRANSACTION READ ONLY"))
                    session.execute(text("SET LOCAL statement_timeout = '1800ms'"))
                principal = session.scalar(
                    select(AuthPrincipal).where(
                        AuthPrincipal.issuer == identity.issuer,
                        AuthPrincipal.subject == identity.subject,
                        AuthPrincipal.scope_id == settings.auth_personal_scope_id,
                        AuthPrincipal.active.is_(True),
                    )
                )
                if principal is None:
                    raise HTTPException(
                        status_code=401, detail="Authentication required"
                    )
                result = read_finance_context(
                    session,
                    body,
                    principal_scope_id=principal.scope_id,
                )
                encoded = result.model_dump_json().encode("utf-8")
                if len(encoded) > body.max_bytes:
                    raise HTTPException(status_code=413, detail="Response is too large")
    except FinanceContextNotFound as error:
        raise HTTPException(
            status_code=404, detail="Selected Finance context not found"
        ) from error
    except FinanceContextSelectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SQLAlchemyError:
        raise
    return Response(
        content=encoded,
        status_code=status.HTTP_200_OK,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )
