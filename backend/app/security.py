"""Demo-session resolution and short-lived HMAC approval/caller contexts."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Any

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.domain_errors import DomainError, forbidden
from app.models import DemoUser


def _secret() -> bytes:
    configured = get_settings().grant_signing_secret
    value = configured.get_secret_value() if configured else ""
    if len(value.encode("utf-8")) < 32:
        raise RuntimeError("GRANT_SIGNING_SECRET must contain at least 32 bytes.")
    return value.encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign_context(claims: dict[str, Any]) -> str:
    payload = _b64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = _b64(hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def verify_context(token: str, expected_type: str, now: int | None = None) -> dict[str, Any]:
    try:
        payload, supplied_signature = token.split(".", 1)
        expected = hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64(supplied_signature), expected):
            raise ValueError("signature")
        claims = json.loads(_unb64(payload))
        current = int(time.time()) if now is None else now
        if claims.get("typ") != expected_type or int(claims["exp"]) <= current:
            raise ValueError("claims")
        uuid.UUID(claims["user_id"])
        return claims
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise forbidden() from exc


def issue_approval_grant(
    user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    snapshot_version: int,
    snapshot_hash: str,
    ttl_seconds: int = 120,
) -> str:
    now = int(time.time())
    return sign_context(
        {
            "typ": "approval",
            "user_id": str(user_id),
            "proposal_id": str(proposal_id),
            "action": "approved",
            "snapshot_version": snapshot_version,
            "snapshot_hash": snapshot_hash,
            "iat": now,
            "exp": now + ttl_seconds,
            "jti": str(uuid.uuid4()),
        }
    )


def issue_actor_context(user_id: uuid.UUID, ttl_seconds: int = 300) -> str:
    now = int(time.time())
    return sign_context(
        {"typ": "actor", "user_id": str(user_id), "iat": now, "exp": now + ttl_seconds}
    )


def resolve_demo_user(request: Request, db: Session = Depends(get_db)) -> DemoUser:
    token = request.cookies.get(get_settings().demo_session_cookie)
    if not token:
        raise HTTPException(status_code=401, detail={"code": "unauthenticated", "message": "Start a demo session first."})
    try:
        claims = verify_context(token, "demo_session")
    except DomainError as exc:
        raise HTTPException(status_code=401, detail={"code": "unauthenticated", "message": "The demo session is invalid or expired."}) from exc
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    user = db.scalar(select(DemoUser).where(DemoUser.session_key_hash == token_hash))
    if user is None or str(user.id) != claims["user_id"]:
        raise HTTPException(status_code=401, detail={"code": "unauthenticated", "message": "The demo session is invalid or expired."})
    return user


def create_demo_session(db: Session, response: Response) -> DemoUser:
    """Issue an HTTP-only opaque cookie for the single synthetic demo user."""

    user = db.scalar(select(DemoUser).order_by(DemoUser.id).with_for_update())
    if user is None:
        raise HTTPException(status_code=503, detail="Synthetic demo data has not been seeded.")
    now = int(time.time())
    raw_token = sign_context(
        {
            "typ": "demo_session",
            "user_id": str(user.id),
            "iat": now,
            "exp": now + get_settings().demo_session_ttl_seconds,
            "nonce": secrets.token_urlsafe(32),
        }
    )
    user.session_key_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    db.commit()
    response.set_cookie(
        key=get_settings().demo_session_cookie,
        value=raw_token,
        httponly=True,
        secure=False,
        samesite="strict",
        max_age=get_settings().demo_session_ttl_seconds,
        path="/",
    )
    return user
