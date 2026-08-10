"""Password gate for the admin console.

SWA Free has no built-in username/password provider, so the check lives here:
PBKDF2 password verification plus an HMAC-signed, HttpOnly session cookie.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.data.tables import TableClient, UpdateMode

COOKIE_NAME = "bc_session"
SESSION_TTL = 12 * 60 * 60
RATE_TABLE = "authattempts"
RATE_WINDOW = 15 * 60
RATE_LIMIT = 10
PBKDF2_PREFIX = "pbkdf2_sha256"


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _secret() -> bytes:
    value = os.environ.get("AUTH_SECRET")
    if not value:
        raise RuntimeError("AUTH_SECRET is not configured")
    return value.encode("utf-8")


def hash_password(plain: str, iterations: int = 200_000) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, iterations)
    return f"{PBKDF2_PREFIX}${iterations}${_b64e(salt)}${_b64e(digest)}"


def verify_password(plain: str, stored: str) -> bool:
    try:
        prefix, iterations, salt, digest = stored.split("$")
        if prefix != PBKDF2_PREFIX:
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), _b64d(salt), int(iterations))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(candidate, _b64d(digest))


def issue_token(username: str) -> str:
    payload = _b64e(json.dumps({"sub": username, "exp": int(time.time()) + SESSION_TTL}).encode("utf-8"))
    signature = _b64e(hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def verify_token(token: str) -> str | None:
    try:
        payload, signature = token.split(".")
        expected = hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64d(signature), expected):
            return None
        claims = json.loads(_b64d(payload))
    except (ValueError, AttributeError, json.JSONDecodeError):
        return None
    if int(claims.get("exp", 0)) < time.time():
        return None
    return claims.get("sub")


def _cookie_value(header: str | None, name: str) -> str | None:
    for chunk in (header or "").split(";"):
        key, _, value = chunk.strip().partition("=")
        if key == name:
            return value
    return None


def current_user(req: Any) -> str | None:
    token = _cookie_value(req.headers.get("Cookie"), COOKIE_NAME)
    return verify_token(token) if token else None


def session_cookie(token: str) -> str:
    return f"{COOKIE_NAME}={token}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}"


def expired_cookie() -> str:
    return f"{COOKIE_NAME}=; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=0"


def _rate_table() -> TableClient:
    client = TableClient.from_connection_string(
        os.environ["STORAGE_CONNECTION_STRING"], table_name=RATE_TABLE
    )
    try:
        client.create_table()
    except ResourceExistsError:
        pass
    return client


def _rate_key(req: Any) -> str:
    source = (req.headers.get("x-forwarded-for") or "unknown").split(",")[0].strip()
    return hmac.new(_secret(), source.encode("utf-8"), hashlib.sha256).hexdigest()


def rate_limited(req: Any) -> bool:
    """True when this client has burned through the failed-login budget."""
    with _rate_table() as table:
        try:
            entity = table.get_entity("rl", _rate_key(req))
        except ResourceNotFoundError:
            return False
        if time.time() - float(entity.get("windowStart", 0)) > RATE_WINDOW:
            return False
        return int(entity.get("count", 0)) >= RATE_LIMIT


def record_failure(req: Any) -> None:
    key = _rate_key(req)
    with _rate_table() as table:
        try:
            entity = table.get_entity("rl", key)
            expired = time.time() - float(entity.get("windowStart", 0)) > RATE_WINDOW
            count = 1 if expired else int(entity.get("count", 0)) + 1
            start = time.time() if expired else float(entity.get("windowStart", time.time()))
        except ResourceNotFoundError:
            count, start = 1, time.time()
        table.upsert_entity(
            {"PartitionKey": "rl", "RowKey": key, "count": count, "windowStart": start},
            mode=UpdateMode.REPLACE,
        )


def clear_failures(req: Any) -> None:
    with _rate_table() as table:
        try:
            table.delete_entity("rl", _rate_key(req))
        except ResourceNotFoundError:
            pass
