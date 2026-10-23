"""Deterministic order, policy, proposal, approval, status, and audit services."""

from __future__ import annotations

import hashlib
import hmac
import json
import unicodedata
import uuid
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.domain_errors import DomainError, conflict, forbidden, not_found
from app.models import (
    ApprovalRecord,
    AuditEvent,
    Order,
    OrderItem,
    ReturnProposal,
    ReturnRequest,
)

SNAPSHOT_VERSION = 1
PROPOSAL_TTL = timedelta(minutes=15)
POLICY_VERSION = "demo-1"


def _now() -> datetime:
    return datetime.now(UTC)


def _audit(
    db: Session,
    event_type: str,
    owner_id: uuid.UUID,
    proposal_id: uuid.UUID | None = None,
    request_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            owner_id=owner_id,
            proposal_id=proposal_id,
            request_id=request_id,
            event_type=event_type,
            details=details or {},
        )
    )


def canonical_snapshot_bytes(snapshot: dict[str, Any]) -> bytes:
    """Canonical compact UTF-8 JSON with sorted keys and NFC strings."""

    def normalize(value: Any) -> Any:
        if isinstance(value, str):
            return unicodedata.normalize("NFC", value)
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {unicodedata.normalize("NFC", key): normalize(item) for key, item in value.items()}
        return value

    return json.dumps(
        normalize(snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_snapshot_bytes(snapshot)).hexdigest()


def _item_dict(item: OrderItem) -> dict[str, Any]:
    return {
        "order_item_id": item.id,
        "sku": item.sku,
        "product_name": item.product_name,
        "description": item.description,
        "quantity": item.quantity,
        "condition_code": item.condition_code,
    }


def _order_result(order: Order, items: list[OrderItem]) -> dict[str, Any]:
    return {
        "order_id": order.id,
        "external_order_ref": order.external_order_ref,
        "ordered_at": order.ordered_at,
        "delivered_at": order.delivered_at,
        "delivery_status": order.delivery_status,
        "items": [_item_dict(item) for item in items],
    }


def search_orders(db: Session, owner_id: uuid.UUID, query: str) -> list[dict[str, Any]]:
    """Search only this owner's synthetic orders by reference, SKU, or product."""

    normalized = query.strip()
    if not normalized:
        raise DomainError("invalid_input", "Enter an order reference or product detail.", 422)
    pattern = f"%{normalized}%"
    matching_orders = select(OrderItem.order_id).where(
        OrderItem.sku.ilike(pattern) | OrderItem.product_name.ilike(pattern)
    )
    stmt = (
        select(Order)
        .where(
            Order.owner_id == owner_id,
            (Order.external_order_ref.ilike(pattern))
            | (Order.id == _uuid_or_zero(normalized))
            | (Order.id.in_(matching_orders)),
        )
        .order_by(Order.ordered_at.desc())
        .limit(20)
    )
    orders = db.scalars(stmt).all()
    return [_order_result(order, list(db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all())) for order in orders]


def _uuid_or_zero(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        return uuid.UUID(int=0)


def get_order_details(db: Session, owner_id: uuid.UUID, order_id: uuid.UUID) -> dict[str, Any]:
    order = db.scalar(select(Order).where(Order.id == order_id, Order.owner_id == owner_id))
    if order is None:
        raise not_found()
    items = db.scalars(select(OrderItem).where(OrderItem.order_id == order_id)).all()
    return _order_result(order, list(items))


def evaluate_eligibility(order: Order, item: OrderItem, now: datetime | None = None) -> dict[str, Any]:
    """MVP policy: delivered, damaged item, and within 30 days of order date."""

    at = now or _now()
    reasons: list[str] = []
    if order.delivery_status != "delivered":
        reasons.append("Order must be delivered before a replacement can be requested.")
    if item.condition_code != "damaged":
        reasons.append("The item must be marked damaged in the synthetic order record.")
    if order.ordered_at < at - timedelta(days=30):
        reasons.append("The order is outside the 30-day demo return window.")
    return {"eligible": not reasons, "reasons": reasons, "policy_version": POLICY_VERSION}


def _owned_order_item(
    db: Session, owner_id: uuid.UUID, order_id: uuid.UUID, item_id: uuid.UUID
) -> tuple[Order, OrderItem]:
    order = db.scalar(select(Order).where(Order.id == order_id, Order.owner_id == owner_id))
    item = db.scalar(select(OrderItem).where(OrderItem.id == item_id, OrderItem.order_id == order_id))
    if order is None or item is None:
        raise not_found()
    return order, item


def check_eligibility(
    db: Session, owner_id: uuid.UUID, order_id: uuid.UUID, item_id: uuid.UUID
) -> dict[str, Any]:
    order, item = _owned_order_item(db, owner_id, order_id, item_id)
    return evaluate_eligibility(order, item)


def create_proposal(
    db: Session, owner_id: uuid.UUID, order_id: uuid.UUID, item_id: uuid.UUID, resolution: str
) -> dict[str, Any]:
    order, item = _owned_order_item(db, owner_id, order_id, item_id)
    policy = evaluate_eligibility(order, item)
    if not policy["eligible"]:
        raise DomainError("ineligible", "This item is not eligible for a simulated replacement.", 422)
    if resolution != "replacement":
        raise DomainError("invalid_input", "Only simulated replacement is supported.", 422)
    snapshot = {
        "snapshot_version": SNAPSHOT_VERSION,
        "order_id": str(order.id),
        "order_item_id": str(item.id),
        "resolution": resolution,
        "conditions": [
            "This is a simulated replacement request.",
            "No physical replacement will be shipped.",
        ],
    }
    proposal = ReturnProposal(
        owner_id=owner_id,
        order_id=order.id,
        order_item_id=item.id,
        resolution=resolution,
        state="pending",
        action_snapshot=snapshot,
        policy_result=policy,
        expires_at=_now() + PROPOSAL_TTL,
    )
    try:
        db.add(proposal)
        db.flush()
        _audit(db, "proposal_created", owner_id, proposal.id, details={"state": "pending"})
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    return proposal_result(db, proposal)


def _assert_snapshot(proposal: ReturnProposal) -> tuple[int, str]:
    snapshot = proposal.action_snapshot
    try:
        version = snapshot["snapshot_version"]
        if (
            not isinstance(version, int)
            or version != SNAPSHOT_VERSION
            or snapshot["order_id"] != str(proposal.order_id)
            or snapshot["order_item_id"] != str(proposal.order_item_id)
            or snapshot["resolution"] != proposal.resolution
            or not isinstance(snapshot["conditions"], list)
        ):
            raise ValueError("snapshot fields do not match proposal")
    except (KeyError, TypeError, ValueError) as exc:
        raise conflict("snapshot_mismatch", "The proposal snapshot is invalid or has changed.") from exc
    return version, snapshot_hash(snapshot)


def proposal_result(db: Session, proposal: ReturnProposal) -> dict[str, Any]:
    version, digest = _assert_snapshot(proposal)
    request = db.scalar(select(ReturnRequest).where(ReturnRequest.proposal_id == proposal.id))
    return {
        "proposal_id": proposal.id,
        "owner_id": proposal.owner_id,
        "order_id": proposal.order_id,
        "order_item_id": proposal.order_item_id,
        "resolution": proposal.resolution,
        "state": proposal.state,
        "action_snapshot": proposal.action_snapshot,
        "snapshot_version": version,
        "snapshot_hash": digest,
        "policy_result": proposal.policy_result,
        "expires_at": proposal.expires_at,
        "request": request_result(request) if request else None,
    }


def request_result(request: ReturnRequest) -> dict[str, Any]:
    return {
        "request_id": request.id,
        "proposal_id": request.proposal_id,
        "status": request.status,
        "created_at": request.created_at,
        "outcome": "confirmed",
    }


def _expire_locked(db: Session, proposal: ReturnProposal) -> None:
    proposal.state = "expired"
    _audit(db, "proposal_expired", proposal.owner_id, proposal.id, details={"state": "expired"})


def get_proposal(db: Session, owner_id: uuid.UUID, proposal_id: uuid.UUID) -> dict[str, Any]:
    proposal = db.scalar(select(ReturnProposal).where(ReturnProposal.id == proposal_id, ReturnProposal.owner_id == owner_id))
    if proposal is None:
        raise not_found()
    if proposal.state == "pending" and proposal.expires_at and proposal.expires_at <= _now():
        with db.begin_nested():
            proposal = db.scalar(
                select(ReturnProposal).where(ReturnProposal.id == proposal_id).with_for_update()
            )
            if proposal and proposal.state == "pending" and proposal.expires_at and proposal.expires_at <= _now():
                _expire_locked(db, proposal)
        db.commit()
    return proposal_result(db, proposal)


def _validate_snapshot_submission(
    proposal: ReturnProposal, submitted_version: int, submitted_hash: str
) -> str:
    version, digest = _assert_snapshot(proposal)
    if version != submitted_version or not hmac_compare(digest, submitted_hash):
        raise conflict("snapshot_mismatch", "The proposal changed; review the current action before deciding.")
    return digest


def hmac_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


def _check_current_eligibility(db: Session, proposal: ReturnProposal) -> None:
    order = db.scalar(
        select(Order)
        .where(Order.id == proposal.order_id, Order.owner_id == proposal.owner_id)
        .with_for_update()
    )
    item = db.scalar(
        select(OrderItem)
        .where(OrderItem.id == proposal.order_item_id, OrderItem.order_id == proposal.order_id)
        .with_for_update()
    )
    if order is None or item is None:
        raise not_found()
    result = evaluate_eligibility(order, item)
    if not result["eligible"]:
        raise DomainError("ineligible", "Current order data no longer satisfies replacement eligibility.", 409)


def _existing_approved_result(
    db: Session, proposal: ReturnProposal, actor_id: uuid.UUID, expected_hash: str
) -> dict[str, Any] | None:
    approval = db.scalar(select(ApprovalRecord).where(ApprovalRecord.proposal_id == proposal.id))
    request = db.scalar(select(ReturnRequest).where(ReturnRequest.proposal_id == proposal.id))
    if proposal.state != "completed" or approval is None or request is None:
        return None
    if (
        proposal.owner_id != actor_id
        or approval.owner_id != actor_id
        or approval.decision != "approved"
        or approval.actor_type != "user"
        or approval.action_snapshot_hash != expected_hash
        or request.owner_id != actor_id
        or request.approval_id != approval.id
        or request.proposal_id != proposal.id
    ):
        raise conflict()
    return request_result(request)


def approve_from_grant(db: Session, actor_id: uuid.UUID, claims: dict[str, Any]) -> dict[str, Any]:
    """Apply the grant-verified approval inside one PostgreSQL transaction."""

    try:
        proposal_id = uuid.UUID(claims["proposal_id"])
        grant_user = uuid.UUID(claims["user_id"])
        version = int(claims["snapshot_version"])
        grant_hash = str(claims["snapshot_hash"])
        grant_expires_at = int(claims["exp"])
        if grant_user != actor_id or claims.get("action") != "approved":
            raise forbidden()
    except (KeyError, ValueError, TypeError) as exc:
        raise forbidden() from exc

    unconfirmed = False
    expired = False
    try:
        proposal = db.scalar(select(ReturnProposal).where(ReturnProposal.id == proposal_id).with_for_update())
        if proposal is None or proposal.owner_id != actor_id:
            raise not_found()
        if grant_expires_at <= int(time.time()):
            raise forbidden()
        digest = _validate_snapshot_submission(proposal, version, grant_hash)
        if proposal.state == "completed":
            existing = _existing_approved_result(db, proposal, actor_id, digest)
            if existing is None:
                raise conflict()
            db.commit()
            return existing
        if proposal.state != "pending":
            raise conflict()
        if proposal.expires_at and proposal.expires_at <= _now():
            _expire_locked(db, proposal)
            expired = True
            db.commit()
        else:
            _check_current_eligibility(db, proposal)
            approval = ApprovalRecord(
                id=uuid.uuid4(),
                proposal_id=proposal.id,
                owner_id=actor_id,
                decision="approved",
                action_snapshot_hash=digest,
                actor_type="user",
            )
            request = ReturnRequest(
                proposal_id=proposal.id,
                approval_id=approval.id,
                owner_id=actor_id,
                status="submitted",
            )
            db.add_all([approval, request])
            db.flush()
            proposal.state = "completed"
            _audit(db, "approval_recorded", actor_id, proposal.id, details={"decision": "approved"})
            _audit(db, "request_created", actor_id, proposal.id, request.id, {"status": "submitted"})
            db.commit()
            return request_result(request)
    except SQLAlchemyError:
        db.rollback()
        unconfirmed = True
    except Exception:
        db.rollback()
        raise

    if expired:
        raise conflict("expired", "This proposal has expired.")
    if unconfirmed:
        reconciled = reconcile_request(proposal_id, actor_id, grant_hash)
        if reconciled is not None:
            return reconciled
        return {"proposal_id": proposal_id, "status": "unconfirmed"}
    raise conflict()


def reconcile_request(
    proposal_id: uuid.UUID, actor_id: uuid.UUID, expected_hash: str
) -> dict[str, Any] | None:
    """Read committed state using proposal ID as unique request reference."""

    try:
        with SessionLocal() as check_db:
            proposal = check_db.scalar(select(ReturnProposal).where(ReturnProposal.id == proposal_id))
            if proposal is None or proposal.owner_id != actor_id:
                return None
            version, digest = _assert_snapshot(proposal)
            if not hmac_compare(digest, expected_hash):
                return None
            return _existing_approved_result(check_db, proposal, actor_id, digest)
    except (SQLAlchemyError, DomainError):
        return None


def decline_proposal(
    db: Session,
    actor_id: uuid.UUID,
    proposal_id: uuid.UUID,
    submitted_version: int,
    submitted_hash: str,
) -> dict[str, Any]:
    proposal = db.scalar(select(ReturnProposal).where(ReturnProposal.id == proposal_id).with_for_update())
    if proposal is None or proposal.owner_id != actor_id:
        raise not_found()
    digest = _validate_snapshot_submission(proposal, submitted_version, submitted_hash)
    approval = db.scalar(select(ApprovalRecord).where(ApprovalRecord.proposal_id == proposal.id))
    request = db.scalar(select(ReturnRequest).where(ReturnRequest.proposal_id == proposal.id))
    if proposal.state == "declined" and approval and approval.decision == "declined" and approval.owner_id == actor_id and approval.action_snapshot_hash == digest and request is None:
        return {"proposal_id": proposal.id, "state": "declined", "decision": "declined"}
    if proposal.state != "pending":
        raise conflict()
    if proposal.expires_at and proposal.expires_at <= _now():
        _expire_locked(db, proposal)
        db.commit()
        raise conflict("expired", "This proposal has expired.")
    record = ApprovalRecord(
        proposal_id=proposal.id,
        owner_id=actor_id,
        decision="declined",
        action_snapshot_hash=digest,
        actor_type="user",
    )
    db.add(record)
    proposal.state = "declined"
    _audit(db, "approval_recorded", actor_id, proposal.id, details={"decision": "declined"})
    _audit(db, "proposal_declined", actor_id, proposal.id, details={"state": "declined"})
    db.commit()
    return {"proposal_id": proposal.id, "state": "declined", "decision": "declined"}


def get_request_status(db: Session, actor_id: uuid.UUID, request_id: uuid.UUID) -> dict[str, Any]:
    request = db.scalar(select(ReturnRequest).where(ReturnRequest.id == request_id, ReturnRequest.owner_id == actor_id))
    if request is None:
        raise not_found()
    _audit(db, "request_status_checked", actor_id, request.proposal_id, request.id, {"status": request.status})
    db.commit()
    return request_result(request)


def get_request_history(db: Session, actor_id: uuid.UUID, request_id: uuid.UUID) -> dict[str, Any]:
    result = get_request_status(db, actor_id, request_id)
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.request_id == request_id, AuditEvent.owner_id == actor_id)
        .order_by(AuditEvent.occurred_at.asc())
    ).all()
    return {
        "request": result,
        "events": [
            {"event_type": e.event_type, "occurred_at": e.occurred_at, "details": e.details}
            for e in events
        ],
    }


def order_item_eligibility_result(db: Session, actor_id: uuid.UUID, order_id: uuid.UUID, item_id: uuid.UUID) -> dict[str, Any]:
    return check_eligibility(db, actor_id, order_id, item_id)
