"""Authenticated MCP Streamable HTTP server backed by shared domain services."""

from __future__ import annotations

import contextvars
import hmac
import uuid
from typing import Any, Literal

from mcp.server import MCPServer
from pydantic import BaseModel
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import get_settings
from app.database import SessionLocal
from app.domain_errors import DomainError, forbidden
from app.security import verify_context
from app.services import (
    approve_from_grant,
    check_eligibility,
    get_order_details as domain_get_order_details,
    get_request_status,
    search_orders,
)


class ServerStatus(BaseModel):
    status: Literal["ok"]
    service: Literal["returnpilot-mcp"]


_trusted_actor: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "returnpilot_trusted_actor", default=None
)
_verified_approval: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "returnpilot_verified_approval", default=None
)


def _actor() -> uuid.UUID:
    actor = _trusted_actor.get()
    if actor is None:
        raise forbidden()
    return actor


def _tool_error(exc: DomainError) -> dict[str, Any]:
    return {"error": {"code": exc.code, "message": exc.message}}


class BearerAndActorMiddleware:
    """Authenticate FastAPI and verify its server-signed actor context."""

    def __init__(self, app: ASGIApp, secret: str) -> None:
        self.app = app
        self.expected = secret.encode("utf-8")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        authorization = headers.get(b"authorization", b"")
        scheme, separator, supplied = authorization.partition(b" ")
        authorized = (
            separator == b" "
            and scheme.lower() == b"bearer"
            and hmac.compare_digest(supplied, self.expected)
        )
        if not authorized:
            response = JSONResponse(
                {"error": "unauthorized", "message": "A trusted backend credential is required."},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        actor_token = headers.get(b"x-returnpilot-actor")
        grant_token = headers.get(b"x-returnpilot-approval-grant")
        actor_id = None
        approval_claims = None
        if actor_token:
            try:
                claims = verify_context(actor_token.decode("ascii"), "actor")
                actor_id = uuid.UUID(claims["user_id"])
            except (DomainError, UnicodeDecodeError, ValueError):
                response = JSONResponse(
                    {"error": "unauthorized", "message": "The trusted caller context is invalid."},
                    status_code=401,
                )
                await response(scope, receive, send)
                return
        if grant_token:
            try:
                approval_claims = verify_context(grant_token.decode("ascii"), "approval")
                if actor_id is None or uuid.UUID(approval_claims["user_id"]) != actor_id:
                    raise ValueError("grant caller mismatch")
            except (DomainError, UnicodeDecodeError, ValueError):
                response = JSONResponse(
                    {"error": "unauthorized", "message": "The approval context is invalid."},
                    status_code=401,
                )
                await response(scope, receive, send)
                return
        actor_context = _trusted_actor.set(actor_id)
        approval_context = _verified_approval.set(approval_claims)
        try:
            await self.app(scope, receive, send)
        finally:
            _verified_approval.reset(approval_context)
            _trusted_actor.reset(actor_context)


settings = get_settings()
shared_secret = settings.mcp_shared_secret.get_secret_value() if settings.mcp_shared_secret else ""
if not shared_secret:
    raise RuntimeError("Set a non-empty MCP_SHARED_SECRET before starting the MCP server.")

mcp = MCPServer("ReturnPilot")


@mcp.tool()
def server_status(component: Literal["mcp"]) -> ServerStatus:
    """Return process status without accessing business data."""

    return ServerStatus(status="ok", service="returnpilot-mcp")


@mcp.tool()
def find_order(query: str) -> dict[str, Any]:
    """Search the authenticated demo user's synthetic orders."""

    try:
        with SessionLocal() as db:
            return {"matches": search_orders(db, _actor(), query)}
    except DomainError as exc:
        return _tool_error(exc)


@mcp.tool()
def get_order_details(order_id: str) -> dict[str, Any]:
    """Return an order only when it belongs to the signed caller context."""

    try:
        with SessionLocal() as db:
            return {"order": domain_get_order_details(db, _actor(), uuid.UUID(order_id))}
    except (DomainError, ValueError) as exc:
        return _tool_error(exc if isinstance(exc, DomainError) else DomainError("invalid_input", "Order ID must be a UUID.", 422))


@mcp.tool()
def check_return_eligibility(order_id: str, order_item_id: str) -> dict[str, Any]:
    """Evaluate deterministic policy for an owner-scoped order item."""

    try:
        with SessionLocal() as db:
            result = check_eligibility(db, _actor(), uuid.UUID(order_id), uuid.UUID(order_item_id))
            return {"eligibility": result}
    except (DomainError, ValueError) as exc:
        return _tool_error(exc if isinstance(exc, DomainError) else DomainError("invalid_input", "Order and item IDs must be UUIDs.", 422))


@mcp.tool()
def create_return_request() -> dict[str, Any]:
    """Execute only a grant bound by the authenticated FastAPI HTTP caller context."""

    try:
        actor_id = _actor()
        claims = _verified_approval.get()
        if claims is None:
            raise forbidden()
        with SessionLocal() as db:
            result = approve_from_grant(db, actor_id, claims)
            return result
    except DomainError as exc:
        return _tool_error(exc)


@mcp.tool()
def get_return_status(request_id: str) -> dict[str, Any]:
    """Read the authenticated user's persisted request status and audit it."""

    try:
        with SessionLocal() as db:
            return get_request_status(db, _actor(), uuid.UUID(request_id))
    except (DomainError, ValueError) as exc:
        return _tool_error(exc if isinstance(exc, DomainError) else DomainError("invalid_input", "Request ID must be a UUID.", 422))


mcp_http_app = mcp.streamable_http_app(json_response=True, stateless_http=True)
app = BearerAndActorMiddleware(mcp_http_app, shared_secret)
