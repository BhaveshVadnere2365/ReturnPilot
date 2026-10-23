"""Create the approved PostgreSQL data model.

Revision ID: 20261017_0001
Revises:
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261017_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("session_key_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_key_hash", name="uq_demo_users_session_key_hash"),
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("external_order_ref", sa.String(80), nullable=False),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "delivery_status IN ('in_transit', 'delivered', 'delayed', 'cancelled')",
            name="ck_orders_delivery_status",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["demo_users.id"], name="fk_orders_owner_id_demo_users"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "external_order_ref", name="uq_orders_owner_external_ref"),
        sa.UniqueConstraint("owner_id", "id", name="uq_orders_owner_id"),
    )
    op.create_table(
        "order_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(100), nullable=False),
        sa.Column("product_name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("condition_code", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name="fk_order_items_order_id_orders", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "order_id", name="uq_order_items_id_order_id"),
    )
    op.create_table(
        "return_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("order_item_id", sa.Uuid(), nullable=False),
        sa.Column("resolution", sa.String(30), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("action_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy_result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("state IN ('pending', 'declined', 'expired', 'completed')", name="ck_return_proposals_state"),
        sa.ForeignKeyConstraint(["order_item_id", "order_id"], ["order_items.id", "order_items.order_id"], name="fk_proposals_item_order_items", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name="fk_proposals_order_id_orders", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_item_id"], ["order_items.id"], name="fk_proposals_order_item_id_order_items", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id", "order_id"], ["orders.owner_id", "orders.id"], name="fk_proposals_owner_order_orders", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["demo_users.id"], name="fk_proposals_owner_id_demo_users"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "owner_id", name="uq_proposals_id_owner_id"),
    )
    op.create_table(
        "approval_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("action_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.CheckConstraint("decision IN ('approved', 'declined')", name="ck_approvals_decision"),
        sa.CheckConstraint("action_snapshot_hash ~ '^[0-9a-f]{64}$'", name="ck_approvals_snapshot_hash_sha256"),
        sa.ForeignKeyConstraint(["owner_id"], ["demo_users.id"], name="fk_approvals_owner_id_demo_users"),
        sa.ForeignKeyConstraint(["proposal_id", "owner_id"], ["return_proposals.id", "return_proposals.owner_id"], name="fk_approvals_proposal_owner_proposals", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["proposal_id"], ["return_proposals.id"], name="fk_approvals_proposal_id_proposals", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "proposal_id", name="uq_approvals_id_proposal"),
        sa.UniqueConstraint("proposal_id", name="uq_approvals_proposal_id"),
        sa.UniqueConstraint("proposal_id", "owner_id", name="uq_approvals_proposal_owner"),
    )
    op.create_table(
        "return_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('submitted')", name="ck_return_requests_status"),
        sa.ForeignKeyConstraint(["approval_id", "proposal_id"], ["approval_records.id", "approval_records.proposal_id"], name="fk_requests_approval_proposal_approvals", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approval_id"], ["approval_records.id"], name="fk_requests_approval_id_approvals", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["demo_users.id"], name="fk_requests_owner_id_demo_users"),
        sa.ForeignKeyConstraint(["proposal_id", "owner_id"], ["return_proposals.id", "return_proposals.owner_id"], name="fk_requests_proposal_owner_proposals", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["proposal_id"], ["return_proposals.id"], name="fk_requests_proposal_id_proposals", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("approval_id", name="uq_requests_approval_id"),
        sa.UniqueConstraint("proposal_id", name="uq_requests_proposal_id"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid()),
        sa.Column("proposal_id", sa.Uuid()),
        sa.Column("request_id", sa.Uuid()),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("correlation_id", sa.Uuid()),
        sa.CheckConstraint("event_type IN ('proposal_created', 'approval_recorded', 'request_created', 'proposal_declined', 'proposal_expired', 'request_status_checked')", name="ck_audit_events_event_type"),
        sa.ForeignKeyConstraint(["owner_id"], ["demo_users.id"], name="fk_audit_owner_id_demo_users"),
        sa.ForeignKeyConstraint(["proposal_id"], ["return_proposals.id"], name="fk_audit_proposal_id_proposals"),
        sa.ForeignKeyConstraint(["request_id"], ["return_requests.id"], name="fk_audit_request_id_requests"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orders_owner_ordered_at", "orders", ["owner_id", sa.text("ordered_at DESC")])
    op.create_index("ix_order_items_order_sku", "order_items", ["order_id", "sku"])
    op.create_index("ix_proposals_owner_created", "return_proposals", ["owner_id", sa.text("created_at DESC")])
    op.create_index("ix_proposals_order_item", "return_proposals", ["order_id", "order_item_id"])
    op.create_index("ix_proposals_state_expires", "return_proposals", ["state", "expires_at"])
    op.create_index("ix_requests_owner_created", "return_requests", ["owner_id", sa.text("created_at DESC")])
    op.create_index("ix_requests_owner_status", "return_requests", ["owner_id", "status"])
    op.create_index("ix_audit_owner_occurred", "audit_events", ["owner_id", sa.text("occurred_at DESC")])
    op.create_index("ix_audit_proposal_occurred", "audit_events", ["proposal_id", "occurred_at"])
    op.create_index("ix_audit_request_occurred", "audit_events", ["request_id", "occurred_at"])


def downgrade() -> None:
    for name, table in (
        ("ix_audit_request_occurred", "audit_events"),
        ("ix_audit_proposal_occurred", "audit_events"),
        ("ix_audit_owner_occurred", "audit_events"),
        ("ix_requests_owner_status", "return_requests"),
        ("ix_requests_owner_created", "return_requests"),
        ("ix_proposals_state_expires", "return_proposals"),
        ("ix_proposals_order_item", "return_proposals"),
        ("ix_proposals_owner_created", "return_proposals"),
        ("ix_order_items_order_sku", "order_items"),
        ("ix_orders_owner_ordered_at", "orders"),
    ):
        op.drop_index(name, table_name=table)
    for table in ("audit_events", "return_requests", "approval_records", "return_proposals", "order_items", "orders", "demo_users"):
        op.drop_table(table)
