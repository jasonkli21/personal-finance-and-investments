"""Transport the existing two auth cookies through Firebase's __session cookie.

OIDC state remains signed by Starlette/Authlib; the session token still resolves
only through the revocable DB session. This layer changes edge transport only.
"""

from http.cookies import SimpleCookie

from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.oidc import OIDC_TRANSACTION_COOKIE
from app.auth.service import SESSION_COOKIE


class FirebaseCookieTransport:
    def __init__(self, app: ASGIApp, *, secret_key: str, max_age: int) -> None:
        self.app = app
        self.serializer = URLSafeTimedSerializer(
            secret_key, salt="firebase-auth-transport-v1"
        )
        self.max_age = max_age

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cookies: SimpleCookie = SimpleCookie()
        cookies.load(Headers(scope=scope).get("cookie", ""))
        values: dict[str, str] = {}
        if "__session" in cookies:
            try:
                decoded = self.serializer.loads(
                    cookies["__session"].value, max_age=self.max_age
                )
                if isinstance(decoded, dict):
                    values = {
                        k: v
                        for k, v in decoded.items()
                        if k in {SESSION_COOKIE, OIDC_TRANSACTION_COOKIE}
                        and isinstance(v, str)
                    }
            except BadSignature:
                pass
        # Ignore internal cookie names arriving directly from a caller. The
        # forwarded transport is the sole source at the cloud edge.
        internal: SimpleCookie = SimpleCookie()
        for name, value in values.items():
            internal[name] = value
        headers = MutableHeaders(scope=scope)
        headers["cookie"] = "; ".join(
            f"{name}={morsel.coded_value}" for name, morsel in internal.items()
        )

        async def send_response(message: Message) -> None:
            if message["type"] == "http.response.start":
                retained = []
                changed = False
                for name, value in message.get("headers", []):
                    if name.lower() == b"set-cookie":
                        outgoing: SimpleCookie = SimpleCookie()
                        outgoing.load(value.decode("latin-1"))
                        matched = False
                        for key in (SESSION_COOKIE, OIDC_TRANSACTION_COOKIE):
                            if key in outgoing:
                                matched = changed = True
                                if outgoing[key]["max-age"] == "0":
                                    values.pop(key, None)
                                else:
                                    values[key] = outgoing[key].value
                        if matched:
                            continue
                    retained.append((name, value))
                message["headers"] = retained
                if changed:
                    cookie: SimpleCookie = SimpleCookie()
                    cookie["__session"] = (
                        self.serializer.dumps(values) if values else ""
                    )
                    cookie["__session"]["path"] = "/"
                    cookie["__session"]["max-age"] = str(self.max_age if values else 0)
                    cookie["__session"]["httponly"] = True
                    cookie["__session"]["secure"] = True
                    cookie["__session"]["samesite"] = "lax"
                    MutableHeaders(scope=message).append(
                        "set-cookie", cookie.output(header="").strip()
                    )
            await send(message)

        await self.app(scope, receive, send_response)


class ApiPrefixTransport:
    """Firebase preserves the /api prefix; local Vite already strips it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/api/"):
            scope = dict(scope)
            scope["path"] = scope["path"][4:]
            scope["raw_path"] = scope["path"].encode("utf-8")
        await self.app(scope, receive, send)
