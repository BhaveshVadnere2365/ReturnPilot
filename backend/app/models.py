"""SQLAlchemy models matching the approved PostgreSQL data model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def uuid_column() -> Mapped[uuid.UUID]:
    """Create a UUID primary-key column with an application-side default."""

    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class DemoUser(Base):
    __tablename__ = "demo_users"
    __table_args__ = (
        UniqueConstraint("session_key_hash", name="uq_demo_users_session_key_hash"),
    )

    id: Mapped[uuid.UUID] = uuid_column()
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    session_key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("owner_id", "external_order_ref", name="uq_orders_owner_external_ref"),
        UniqueConstraint("owner_id", "id", name="uq_orders_owner_id"),
        CheckConstraint(
            "delivery_status IN ('in_transit', 'delivered', 'delayed', 'cancelled')",
            name="ck_orders_delivery_status",
        ),
        Index("ix_orders_owner_ordered_at", "owner_id", desc("ordered_at")),
    )

    id: Mapped[uuid.UUID] = uuid_column()
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("demo_users.id", name="fk_orders_owner_id_demo_users"), nullable=False
    )
    external_order_ref: Mapped[str] = mapped_column(String(80), nullable=False)
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name="fk_order_items_order_id_orders", ondelete="RESTRICT"
        ),
        UniqueConstraint("id", "order_id", name="uq_order_items_id_order_id"),
        CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        Index("ix_order_items_order_sku", "order_id", "sku"),
    )

    id: Mapped[uuid.UUID] = uuid_column()
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    condition_code: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReturnProposal(Base):
    __tablename__ = "return_proposals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "order_id"],
            ["orders.owner_id", "orders.id"],
            name="fk_proposals_owner_order_orders",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["order_item_id", "order_id"],
            ["order_items.id", "order_items.order_id"],
            name="fk_proposals_item_order_items",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "owner_id", name="uq_proposals_id_owner_id"),
        CheckConstraint(
            "state IN ('pending', 'declined', 'expired', 'completed')",
            name="ck_return_proposals_state",
        ),
        Index("ix_proposals_owner_created", "owner_id", desc("created_at")),
        Index("ix_proposals_order_item", "order_id", "order_item_id"),
        Index("ix_proposals_state_expires", "state", "expires_at"),
    )

    id: Mapped[uuid.UUID] = uuid_column()
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("demo_users.id", name="fk_proposals_owner_id_demo_users"), nullable=False
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", name="fk_proposals_order_id_orders", ondelete="RESTRICT"),
        nullable=False,
    )
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("order_items.id", name="fk_proposals_order_item_id_order_items", ondelete="RESTRICT"),
        nullable=False,
    )
    resolution: Mapped[str] = mapped_column(String(30), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    action_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    policy_result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ApprovalRecord(Base):
    __tablename__ = "approval_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["proposal_id", "owner_id"],
            ["return_proposals.id", "return_proposals.owner_id"],
            name="fk_approvals_proposal_owner_proposals",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("proposal_id", name="uq_approvals_proposal_id"),
        UniqueConstraint("proposal_id", "owner_id", name="uq_approvals_proposal_owner"),
        UniqueConstraint("id", "proposal_id", name="uq_approvals_id_proposal"),
        CheckConstraint("decision IN ('approved', 'declined')", name="ck_approvals_decision"),
        CheckConstraint(
            "action_snapshot_hash ~ '^[0-9a-f]{64}$'", name="ck_approvals_snapshot_hash_sha256"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_column()
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("return_proposals.id", name="fk_approvals_proposal_id_proposals", ondelete="RESTRICT"),
        nullable=False,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("demo_users.id", name="fk_approvals_owner_id_demo_users"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    action_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)


class ReturnRequest(Base):
    __tablename__ = "return_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["proposal_id", "owner_id"],
            ["return_proposals.id", "return_proposals.owner_id"],
            name="fk_requests_proposal_owner_proposals",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("proposal_id", name="uq_requests_proposal_id"),
        UniqueConstraint("approval_id", name="uq_requests_approval_id"),
        ForeignKeyConstraint(
            ["approval_id", "proposal_id"],
            ["approval_records.id", "approval_records.proposal_id"],
            name="fk_requests_approval_proposal_approvals",
            ondelete="RESTRICT",
        ),
        CheckConstraint("status IN ('submitted')", name="ck_return_requests_status"),
        Index("ix_requests_owner_created", "owner_id", desc("created_at")),
        Index("ix_requests_owner_status", "owner_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_column()
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("return_proposals.id", name="fk_requests_proposal_id_proposals", ondelete="RESTRICT"),
        nullable=False,
    )
    approval_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approval_records.id", name="fk_requests_approval_id_approvals", ondelete="RESTRICT"),
        nullable=False,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("demo_users.id", name="fk_requests_owner_id_demo_users"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('proposal_created', 'approval_recorded', 'request_created', "
            "'proposal_declined', 'proposal_expired', 'request_status_checked')",
            name="ck_audit_events_event_type",
        ),
        Index("ix_audit_owner_occurred", "owner_id", desc("occurred_at")),
        Index("ix_audit_proposal_occurred", "proposal_id", "occurred_at"),
        Index("ix_audit_request_occurred", "request_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = uuid_column()
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("demo_users.id", name="fk_audit_owner_id_demo_users")
    )
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("return_proposals.id", name="fk_audit_proposal_id_proposals")
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("return_requests.id", name="fk_audit_request_id_requests")
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
