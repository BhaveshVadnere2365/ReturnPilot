"""FastAPI REST boundary for the trusted demo-session and return workflow."""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, HTTPException, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.conversation import ConversationInput, ConversationOutput, handle_conversation
from app.domain_errors import DomainError
from app.mcp_client import open_authenticated_mcp_client
from app.models import DemoUser
from app.schemas import (
    DecisionInput,
    DeclineView,
    EligibilityResult,
    OrderMatch,
    ProposalCreate,
    ProposalView,
    RequestHistory,
    RequestView,
    UnconfirmedView,
)
from app.security import create_demo_session, issue_approval_grant, resolve_demo_user
from app.services import (
    check_eligibility,
    create_proposal,
    decline_proposal,
    get_proposal,
    get_request_history,
    get_request_status,
    reconcile_request,
    search_orders,
)

app = FastAPI(title="ReturnPilot API", version="0.2.0")


@app.exception_handler(DomainError)
async def domain_error_handler(_request, exc: DomainError):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": {"code": exc.code, "message": exc.message}},
    )


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database is unavailable") from exc
    return {"status": "ok", "database": "connected"}


@app.post("/api/demo/session")
def start_demo_session(response: Response, db: Session = Depends(get_db)) -> dict[str, str]:
    user = create_demo_session(db, response)
    return {"status": "ready", "display_name": user.display_name}


@app.post("/api/conversation", response_model=ConversationOutput)
async def conversation(
    payload: ConversationInput,
    user: DemoUser = Depends(resolve_demo_user),
) -> ConversationOutput:
    """Handle one authenticated assistant turn; identity comes only from the demo session."""
    return await handle_conversation(user, payload.message)


@app.get("/api/orders", response_model=dict[str, list[OrderMatch]])
def find_orders(
    query: str,
    user: DemoUser = Depends(resolve_demo_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"matches": search_orders(db, user.id, query)}


@app.get("/api/orders/{order_id}", response_model=OrderMatch)
def order_details(
    order_id: uuid.UUID,
    user: DemoUser = Depends(resolve_demo_user),
    db: Session = Depends(get_db),
) -> dict:
    from app.services import get_order_details

    return get_order_details(db, user.id, order_id)


@app.get("/api/orders/{order_id}/items/{item_id}/eligibility", response_model=EligibilityResult)
def eligibility(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    user: DemoUser = Depends(resolve_demo_user),
    db: Session = Depends(get_db),
) -> dict:
    return check_eligibility(db, user.id, order_id, item_id)


@app.post("/api/proposals", response_model=ProposalView)
def propose(
    payload: ProposalCreate,
    user: DemoUser = Depends(resolve_demo_user),
    db: Session = Depends(get_db),
) -> dict:
    return create_proposal(db, user.id, payload.order_id, payload.order_item_id, payload.resolution)


@app.get("/api/proposals/{proposal_id}", response_model=ProposalView)
def proposal(
    proposal_id: uuid.UUID,
    user: DemoUser = Depends(resolve_demo_user),
    db: Session = Depends(get_db),
) -> dict:
    return get_proposal(db, user.id, proposal_id)


@app.post("/api/proposals/{proposal_id}/approve", response_model=RequestView | UnconfirmedView)
async def approve(
    proposal_id: uuid.UUID,
    payload: DecisionInput,
    user: DemoUser = Depends(resolve_demo_user),
    db: Session = Depends(get_db),
) -> dict:
    """Explicit UI decision issues a grant, then FastAPI initiates MCP execution."""

    current = get_proposal(db, user.id, proposal_id)
    if current["snapshot_version"] != payload.snapshot_version or current["snapshot_hash"] != payload.snapshot_hash:
        raise DomainError("snapshot_mismatch", "The proposal changed; review the current action before deciding.", 409)
    if current["state"] == "completed":
        return _reconcile_or_conflict(proposal_id, user.id, payload.snapshot_hash)
    grant = issue_approval_grant(user.id, proposal_id, payload.snapshot_version, payload.snapshot_hash)
    try:
        async with open_authenticated_mcp_client(user.id, grant) as client:
            result = await client.call_tool("create_return_request", {})
        if result.structured_content and result.structured_content.get("status") == "unconfirmed":
            return {"proposal_id": proposal_id, "status": "unconfirmed", "message": "Outcome not yet confirmed. Check request status before retrying."}
        tool_error = (result.structured_content or {}).get("error")
        if result.is_error or tool_error:
            code = tool_error.get("code", "temporarily_unavailable") if tool_error else "temporarily_unavailable"
            message = tool_error.get("message", "The request could not be confirmed.") if tool_error else "The request could not be confirmed."
            status = 404 if code == "not_found" else 403 if code == "forbidden" else 409 if code in {"invalid_state", "expired", "snapshot_mismatch", "ineligible"} else 503
            raise DomainError(code, message, status)
        return result.structured_content or {}
    except DomainError:
        raise
    except Exception:
        reconciled = reconcile_request(proposal_id, user.id, payload.snapshot_hash)
        if reconciled is not None:
            return reconciled
        return {"proposal_id": proposal_id, "status": "unconfirmed", "message": "Outcome not yet confirmed. Check request status before retrying."}


def _reconcile_or_conflict(proposal_id: uuid.UUID, owner_id: uuid.UUID, digest: str) -> dict:
    request = reconcile_request(proposal_id, owner_id, digest)
    if request is not None:
        return request
    raise DomainError("invalid_state", "The proposal is no longer available for approval.", 409)


@app.post("/api/proposals/{proposal_id}/decline", response_model=DeclineView)
def decline(
    proposal_id: uuid.UUID,
    payload: DecisionInput,
    user: DemoUser = Depends(resolve_demo_user),
    db: Session = Depends(get_db),
) -> dict:
    return decline_proposal(db, user.id, proposal_id, payload.snapshot_version, payload.snapshot_hash)


@app.get("/api/requests/{request_id}", response_model=RequestView)
def request_status(
    request_id: uuid.UUID,
    user: DemoUser = Depends(resolve_demo_user),
    db: Session = Depends(get_db),
) -> dict:
    return get_request_status(db, user.id, request_id)


@app.get("/api/requests/{request_id}/history", response_model=RequestHistory)
def request_history(
    request_id: uuid.UUID,
    user: DemoUser = Depends(resolve_demo_user),
    db: Session = Depends(get_db),
) -> dict:
    return get_request_history(db, user.id, request_id)
