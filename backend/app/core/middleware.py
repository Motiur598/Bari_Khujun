"""HTTP hardening middleware: security headers and a request-body ceiling."""

import re

from app.core.config import settings

DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")

# The API only ever serves JSON and file downloads, so nothing it returns needs to run scripts or be framed.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
# Swagger UI loads its bundle from jsDelivr and boots with an inline script.
DOCS_CSP = (
    "default-src 'none'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: https://fastapi.tiangolo.com; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
)


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        is_docs = scope["path"].startswith(DOCS_PATHS)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in _MANAGED]
                headers += [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"content-security-policy", (DOCS_CSP if is_docs else API_CSP).encode()),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
                    (b"cross-origin-opener-policy", b"same-origin"),
                    (b"cross-origin-resource-policy", b"same-site"),
                ]
                if not is_docs and not any(key.lower() == b"cache-control" for key, _ in headers):
                    # Responses carry personal data; keep them out of shared and browser caches. A response that sets
                    # its own policy (public listing photos, private file downloads) keeps it.
                    headers.append((b"cache-control", b"no-store"))
                if settings.enable_hsts:
                    headers.append((b"strict-transport-security", b"max-age=63072000; includeSubDomains"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


_MANAGED = {
    b"x-content-type-options", b"x-frame-options", b"referrer-policy", b"content-security-policy",
    b"permissions-policy", b"cross-origin-opener-policy", b"cross-origin-resource-policy",
}


class BodySizeLimitMiddleware:
    """Refuse oversized bodies before FastAPI spools them to disk (413), by header and by bytes actually read.

    `overrides` is a list of (path regex, ceiling) for the few routes that take bigger uploads, such as videos.
    """

    def __init__(self, app, max_bytes: int, overrides: list[tuple[str, int]] = ()):
        self.app = app
        self.default_max_bytes = max_bytes
        self.overrides = [(re.compile(pattern), limit) for pattern, limit in overrides]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        max_bytes = next((limit for pattern, limit in self.overrides if pattern.fullmatch(scope["path"])), self.default_max_bytes)
        length = dict(scope.get("headers") or []).get(b"content-length")
        if length is not None and length.isdigit() and int(length) > max_bytes:
            return await _too_large(send)

        received = 0

        async def counting_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_bytes:
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, counting_receive, send)
        except _BodyTooLarge:
            await _too_large(send)


class _BodyTooLarge(Exception):
    pass


async def _too_large(send) -> None:
    body = b'{"detail":"Request body is too large"}'
    await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
