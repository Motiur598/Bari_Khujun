"""Input sanitising: NoSQL-operator rejection, HTML stripping and safe ObjectId parsing."""

import html
import json
import re
from typing import Annotated, Any
from urllib.parse import parse_qsl

import nh3
from bson import ObjectId
from fastapi import HTTPException, status
from pydantic import BaseModel, BeforeValidator, ConfigDict

# ---------------------------------------------------------------- ObjectIds


def parse_object_id(value: Any) -> ObjectId:
    """Turn a client-supplied id into an ObjectId, or fail with a 400 (never a 500 from bson's InvalidId)."""
    if not isinstance(value, str) or not ObjectId.is_valid(value):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid ID format")
    return ObjectId(value)


# ---------------------------------------------------------------- HTML / XSS

_TAG_LIKE = re.compile(r"<\s*/?\s*[a-zA-Z!?][^>]*>")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def strip_html(value: str) -> str:
    """Plain text with every HTML tag removed (script/style contents included).

    Entities are decoded after each pass and the text cleaned again, so tags hidden as &lt;script&gt; are caught
    too. The result is stored as plain text; React escapes it again when rendering.
    """
    text = _CONTROL_CHARS.sub("", value)
    for _ in range(5):
        cleaned = html.unescape(nh3.clean(text, tags=set()))
        if cleaned == text:
            break
        text = cleaned
    return _TAG_LIKE.sub("", text).strip()


def _strip_if_text(value: Any) -> Any:
    return strip_html(value) if isinstance(value, str) else value


def clean_text(value: str | None) -> str | None:
    """For Form() fields, which don't go through a Pydantic model."""
    return None if value is None else strip_html(value)


# Free text a user types (titles, descriptions, names, notes, comments). Stripping runs before the length
# limits, so "<script>…</script>" can't sneak an empty title past min_length.
SafeText = Annotated[str, BeforeValidator(_strip_if_text)]


class RequestModel(BaseModel):
    """Base for every request body and query model: unknown fields are rejected, not silently dropped,
    so a client can't slip in "role", "trust_score" or "kyc_status"."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- NoSQL operator guard

# Values that look like a MongoDB operator (e.g. "$ne", "$where") or a JS payload aimed at $where.
_OPERATOR_VALUE = re.compile(
    r"^\s*\$(?:where|ne|eq|gt|gte|lt|lte|in|nin|regex|options|expr|function|accumulator|or|and|nor|not|exists|type|"
    r"elemMatch|all|size|mod|jsonSchema|text|search|lookup|set|unset|inc|push|pull|rename|addToSet|merge|out)\b",
    re.IGNORECASE,
)
MAX_INSPECTED_JSON_BYTES = 1024 * 1024


def find_injection(value: Any, depth: int = 0) -> str | None:
    """Return a description of the first operator-like key or value in a decoded JSON structure, if any."""
    if depth > 32:
        return "nesting too deep"
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or key.startswith("$") or "." in key or "\x00" in key:
                return f"key {key!r}"
            found = find_injection(item, depth + 1)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_injection(item, depth + 1)
            if found:
                return found
    elif isinstance(value, str) and (_OPERATOR_VALUE.match(value) or "\x00" in value):
        return f"value {value[:40]!r}"
    return None


def _query_injection(query_string: bytes) -> str | None:
    for key, value in parse_qsl(query_string.decode("latin-1"), keep_blank_values=True):
        # Catches PHP/qs-style smuggling such as ?email[$ne]=x as well as $-prefixed keys and values.
        if "$" in key or "[" in key or "." in key:
            return f"query key {key!r}"
        if _OPERATOR_VALUE.match(value) or "\x00" in value:
            return f"query value {value[:40]!r}"
    return None


async def _send_rejection(send, reason: str) -> None:
    body = json.dumps({"detail": "Request contains a disallowed operator", "reason": reason}).encode()
    await send({"type": "http.response.start", "status": 400, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class NoSqlInjectionGuard:
    """ASGI middleware: rejects requests whose query string or JSON body carries MongoDB operators.

    Route handlers already build every filter from typed, validated values; this is the outer wall, so a
    future handler that forgets can't be exploited by `{"email": {"$ne": null}}`-style payloads.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        reason = _query_injection(scope.get("query_string", b""))
        if reason:
            return await _send_rejection(send, reason)

        headers = dict(scope.get("headers") or [])
        if not headers.get(b"content-type", b"").startswith(b"application/json"):
            return await self.app(scope, receive, send)

        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunks.append(message.get("body", b""))
            size += len(chunks[-1])
            if size > MAX_INSPECTED_JSON_BYTES:
                return await _send_rejection(send, "JSON body too large to inspect")
            if not message.get("more_body"):
                break
        body = b"".join(chunks)
        if body:
            try:
                reason = find_injection(json.loads(body))
            except (ValueError, UnicodeDecodeError):
                reason = None  # let FastAPI report malformed JSON as a normal 422
            if reason:
                return await _send_rejection(send, reason)

        replayed = False

        async def replay():
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay, send)
