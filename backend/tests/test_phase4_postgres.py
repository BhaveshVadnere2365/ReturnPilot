"""Phase 4 safety/lifecycle tests. These require the configured real PostgreSQL DB."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from app.database import SessionLocal
from app.domain_errors import DomainError
from app.mcp_server import create_return_request
from app.models import (
    ApprovalRecord,
    AuditEvent,
    DemoUser,
    Order,
    OrderItem,
    ReturnProposal,
    ReturnRequest,
)
from app.security import issue_approval_grant, sign_context, verify_context
from app.services import (
    approve_from_grant,
    check_eligibility,
    create_proposal,
    decline_proposal,
    get_proposal,
    get_request_status,
    reconcile_request,
    search_orders,
)


@pytest.fixture
def records():
    owner_id = uuid.uuid4()
    order_id = uuid.uuid4()
    item_id = uuid.uuid4()
    now = datetime.now(UTC)
    with SessionLocal.begin() as db:
        db.add(DemoUser(id=owner_id, display_name="Phase 4 Test", session_key_hash=f"test-{owner_id}"))
        db.add(
            Order(
                id=order_id,
                owner_id=owner_id,
                external_order_ref=f"TEST-{owner_id.hex[:10]}",
                ordered_at=now - timedelta(days=2),
                delivered_at=now - timedelta(days=1),
                delivery_status="delivered",
            )
        )
        db.add(
            OrderItem(
                id=item_id,
                order_id=order_id,
                sku=f"SKU-{owner_id.hex[:8]}",
                product_name="Test damaged device",
                description="Synthetic test fixture",
                quantity=1,
                condition_code="damaged",
            )
        )
    yield owner_id, order_id, item_id
    with SessionLocal.begin() as db:
        proposal_ids = select(ReturnProposal.id).where(ReturnProposal.owner_id == owner_id)
        request_ids = select(ReturnRequest.id).where(ReturnRequest.owner_id == owner_id)
        db.execute(delete(AuditEvent).where(AuditEvent.owner_id == owner_id))
        db.execute(delete(ReturnRequest).where(ReturnRequest.owner_id == owner_id))
        db.execute(delete(ApprovalRecord).where(ApprovalRecord.owner_id == owner_id))
        db.execute(delete(ReturnProposal).where(ReturnProposal.id.in_(proposal_ids)))
        db.execute(delete(OrderItem).where(OrderItem.order_id == order_id))
        db.execute(delete(Order).where(Order.id == order_id))
        db.execute(delete(DemoUser).where(DemoUser.id == owner_id))


def make_proposal(records):
    owner_id, order_id, item_id = records
    with SessionLocal() as db:
        return create_proposal(db, owner_id, order_id, item_id, "replacement")


def grant_for(owner_id, proposal):
    return issue_approval_grant(
        owner_id,
        proposal["proposal_id"],
        proposal["snapshot_version"],
        proposal["snapshot_hash"],
    )


def test_eligibility_matching_ownership_and_snapshot(records):
    owner_id, order_id, item_id = records
    with SessionLocal() as db:
        assert check_eligibility(db, owner_id, order_id, item_id)["eligible"] is True
        matches = search_orders(db, owner_id, f"TEST-{owner_id.hex[:10]}")
        assert len(matches) == 1 and matches[0]["order_id"] == order_id
        proposal = create_proposal(db, owner_id, order_id, item_id, "replacement")
        stored = get_proposal(db, owner_id, proposal["proposal_id"])
        assert stored["action_snapshot"] == {
            "snapshot_version": 1,
            "order_id": str(order_id),
            "order_item_id": str(item_id),
            "resolution": "replacement",
            "conditions": [
                "This is a simulated replacement request.",
                "No physical replacement will be shipped.",
            ],
        }
        assert stored["snapshot_hash"] == proposal["snapshot_hash"]
        with pytest.raises(DomainError) as error:
            check_eligibility(db, uuid.uuid4(), order_id, item_id)
        assert error.value.code == "not_found"


def test_grants_reject_missing_invalid_expired_and_modified(records):
    owner_id, _, _ = records
    proposal = make_proposal(records)
    token = grant_for(owner_id, proposal)
    assert verify_context(token, "approval")["proposal_id"] == str(proposal["proposal_id"])
    altered_payload, signature = token.split(".", 1)
    modified = ("A" if altered_payload[0] != "A" else "B") + altered_payload[1:] + "." + signature
    for invalid in ("", modified, sign_context({"typ": "approval", "user_id": str(owner_id), "exp": 1})):
        with pytest.raises(DomainError):
            verify_context(invalid, "approval")


def test_mismatched_grant_claims_and_caller_owner_are_rejected(records):
    owner_id, _, _ = records
    proposal = make_proposal(records)
    claims = verify_context(grant_for(owner_id, proposal), "approval")
    db = SessionLocal()
    try:
        with pytest.raises(DomainError):
            approve_from_grant(db, uuid.uuid4(), claims)
    finally:
        db.close()

    variants = [
        {**claims, "user_id": str(uuid.uuid4())},
        {**claims, "proposal_id": str(uuid.uuid4())},
        {**claims, "action": "declined"},
        {**claims, "snapshot_version": 99},
        {**claims, "snapshot_hash": "0" * 64},
    ]
    for altered in variants:
        signed_claims = verify_context(sign_context(altered), "approval")
        db = SessionLocal()
        try:
            with pytest.raises(DomainError):
                approve_from_grant(db, owner_id, signed_claims)
        finally:
            db.close()


def test_direct_mcp_tool_without_trusted_caller_cannot_create(records):
    proposal = make_proposal(records)
    claims = verify_context(grant_for(records[0], proposal), "approval")
    result = create_return_request()
    assert result["error"]["code"] == "forbidden"
    with SessionLocal() as db:
        assert db.scalar(select(ReturnRequest).where(ReturnRequest.proposal_id == proposal["proposal_id"])) is None

    import app.mcp_server as mcp_server

    token = mcp_server._trusted_actor.set(records[0])
    try:
        missing = create_return_request()
        assert missing["error"]["code"] == "forbidden"
    finally:
        mcp_server._trusted_actor.reset(token)

    token = mcp_server._trusted_actor.set(uuid.uuid4())
    grant_context = mcp_server._verified_approval.set(claims)
    try:
        mismatched = create_return_request()
        assert mismatched["error"]["code"] == "forbidden"
    finally:
        mcp_server._verified_approval.reset(grant_context)
        mcp_server._trusted_actor.reset(token)
    with SessionLocal() as db:
        assert db.scalar(select(ReturnRequest).where(ReturnRequest.proposal_id == proposal["proposal_id"])) is None


def test_ineligible_and_persisted_snapshot_modification_are_rejected(records):
    owner_id, order_id, item_id = records
    proposal = make_proposal(records)
    with SessionLocal.begin() as db:
        db.get(OrderItem, item_id).condition_code = "new"
    with SessionLocal() as db:
        result = check_eligibility(db, owner_id, order_id, item_id)
        assert result["eligible"] is False
        with pytest.raises(DomainError) as error:
            approve_from_grant(db, owner_id, verify_context(grant_for(owner_id, proposal), "approval"))
        assert error.value.code == "ineligible"
    with SessionLocal.begin() as db:
        row = db.get(ReturnProposal, proposal["proposal_id"])
        changed = dict(row.action_snapshot)
        changed["conditions"] = ["Changed after display"]
        row.action_snapshot = changed
    with SessionLocal() as db:
        with pytest.raises(DomainError) as error:
            approve_from_grant(db, owner_id, verify_context(grant_for(owner_id, proposal), "approval"))
        assert error.value.code == "snapshot_mismatch"


def test_new_proposal_cannot_be_created_for_ineligible_item(records):
    owner_id, order_id, item_id = records
    with SessionLocal.begin() as db:
        db.get(OrderItem, item_id).condition_code = "new"
    with SessionLocal() as db:
        with pytest.raises(DomainError) as error:
            create_proposal(db, owner_id, order_id, item_id, "replacement")
        assert error.value.code == "ineligible"


def test_approval_replay_is_idempotent_and_atomic(records):
    owner_id, _, _ = records
    proposal = make_proposal(records)
    claims = verify_context(grant_for(owner_id, proposal), "approval")
    with SessionLocal() as db:
        first = approve_from_grant(db, owner_id, claims)
    with SessionLocal() as db:
        second = approve_from_grant(db, owner_id, claims)
        assert second["request_id"] == first["request_id"]
        assert db.scalar(select(ApprovalRecord).where(ApprovalRecord.proposal_id == proposal["proposal_id"]))
        assert len(db.scalars(select(ReturnRequest).where(ReturnRequest.proposal_id == proposal["proposal_id"])).all()) == 1
        persisted = db.get(ReturnProposal, proposal["proposal_id"])
        assert persisted.state == "completed"


def test_concurrent_approvals_serialize_to_one_request(records):
    owner_id, _, _ = records
    proposal = make_proposal(records)
    claims = verify_context(grant_for(owner_id, proposal), "approval")

    def approve_once():
        with SessionLocal() as db:
            return approve_from_grant(db, owner_id, claims)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: approve_once(), range(2)))
    assert outcomes[0]["request_id"] == outcomes[1]["request_id"]
    with SessionLocal() as db:
        assert len(db.scalars(select(ApprovalRecord).where(ApprovalRecord.proposal_id == proposal["proposal_id"])).all()) == 1
        assert len(db.scalars(select(ReturnRequest).where(ReturnRequest.proposal_id == proposal["proposal_id"])).all()) == 1


def test_decline_ineligible_expiry_and_audit_events(records):
    owner_id, _, _ = records
    declined = make_proposal(records)
    with SessionLocal() as db:
        result = decline_proposal(
            db,
            owner_id,
            declined["proposal_id"],
            declined["snapshot_version"],
            declined["snapshot_hash"],
        )
        assert result["state"] == "declined"
        assert decline_proposal(
            db,
            owner_id,
            declined["proposal_id"],
            declined["snapshot_version"],
            declined["snapshot_hash"],
        )["state"] == "declined"
        with pytest.raises(DomainError):
            approve_from_grant(db, owner_id, verify_context(grant_for(owner_id, declined), "approval"))

    expiring = make_proposal(records)
    with SessionLocal.begin() as db:
        db.get(ReturnProposal, expiring["proposal_id"]).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with SessionLocal() as db:
        assert get_proposal(db, owner_id, expiring["proposal_id"])["state"] == "expired"

    approved = make_proposal(records)
    claims = verify_context(grant_for(owner_id, approved), "approval")
    with SessionLocal() as db:
        request = approve_from_grant(db, owner_id, claims)
        get_request_status(db, owner_id, request["request_id"])
        events = set(db.scalars(select(AuditEvent.event_type).where(AuditEvent.proposal_id == approved["proposal_id"])).all())
    with SessionLocal() as db:
        decline_events = set(db.scalars(select(AuditEvent.event_type).where(AuditEvent.proposal_id == declined["proposal_id"])).all())
        expiry_events = set(db.scalars(select(AuditEvent.event_type).where(AuditEvent.proposal_id == expiring["proposal_id"])).all())
    assert {"proposal_created", "approval_recorded", "request_created", "request_status_checked"} <= events
    assert {"proposal_created", "approval_recorded", "proposal_declined"} <= decline_events
    assert {"proposal_created", "proposal_expired"} <= expiry_events


def test_rollback_leaves_no_approval_request_or_success_events(records, monkeypatch):
    owner_id, _, _ = records
    proposal = make_proposal(records)
    claims = verify_context(grant_for(owner_id, proposal), "approval")
    import app.services as services

    original = services._audit

    def fail_request_created(db, event_type, *args, **kwargs):
        if event_type == "request_created":
            raise RuntimeError("simulated failure before commit")
        return original(db, event_type, *args, **kwargs)

    monkeypatch.setattr(services, "_audit", fail_request_created)
    with SessionLocal() as db, pytest.raises(RuntimeError):
        approve_from_grant(db, owner_id, claims)
    with SessionLocal() as db:
        assert db.scalar(select(ReturnProposal).where(ReturnProposal.id == proposal["proposal_id"])).state == "pending"
        assert db.scalar(select(ApprovalRecord).where(ApprovalRecord.proposal_id == proposal["proposal_id"])) is None
        assert db.scalar(select(ReturnRequest).where(ReturnRequest.proposal_id == proposal["proposal_id"])) is None
        assert not db.scalars(select(AuditEvent).where(AuditEvent.proposal_id == proposal["proposal_id"], AuditEvent.event_type.in_(["approval_recorded", "request_created"]))).all()


def test_uncertain_commit_reconciliation_returns_only_persisted_result(records):
    owner_id, _, _ = records
    proposal = make_proposal(records)
    claims = verify_context(grant_for(owner_id, proposal), "approval")
    with SessionLocal() as db:
        original_commit = db.commit

        def commit_then_disconnect():
            original_commit()
            raise OperationalError("COMMIT", {}, RuntimeError("connection lost after commit"))

        db.commit = commit_then_disconnect
        result = approve_from_grant(db, owner_id, claims)
    assert result["outcome"] == "confirmed"
    assert reconcile_request(proposal["proposal_id"], owner_id, proposal["snapshot_hash"])["request_id"] == result["request_id"]

    # The caller may retry after losing the original response. The same valid
    # grant must return the committed request instead of creating another one.
    with SessionLocal() as db:
        retried = approve_from_grant(db, owner_id, claims)
    assert retried["request_id"] == result["request_id"]
    with SessionLocal() as db:
        assert len(db.scalars(select(ApprovalRecord).where(ApprovalRecord.proposal_id == proposal["proposal_id"])).all()) == 1
        assert len(db.scalars(select(ReturnRequest).where(ReturnRequest.proposal_id == proposal["proposal_id"])).all()) == 1
        assert db.scalar(select(ReturnProposal).where(ReturnProposal.id == proposal["proposal_id"])).state == "completed"


def test_uncertain_commit_without_visible_result_stays_unconfirmed(records):
    owner_id, _, _ = records
    proposal = make_proposal(records)
    claims = verify_context(grant_for(owner_id, proposal), "approval")
    with SessionLocal() as db:
        def fail_before_commit():
            raise OperationalError("COMMIT", {}, RuntimeError("connection lost"))

        db.commit = fail_before_commit
        result = approve_from_grant(db, owner_id, claims)
    assert result == {"proposal_id": proposal["proposal_id"], "status": "unconfirmed"}
    with SessionLocal() as db:
        assert db.scalar(select(ReturnProposal).where(ReturnProposal.id == proposal["proposal_id"])).state == "pending"
        assert db.scalar(select(ReturnRequest).where(ReturnRequest.proposal_id == proposal["proposal_id"])) is None
