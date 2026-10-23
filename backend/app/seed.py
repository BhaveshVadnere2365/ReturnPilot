"""Repeatably seed synthetic ReturnPilot demo users, orders, and items."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal
from app.models import DemoUser, Order, OrderItem

DEMO_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
ORDER_ONE_ID = uuid.UUID("00000000-0000-4000-8000-000000000101")
ORDER_TWO_ID = uuid.UUID("00000000-0000-4000-8000-000000000102")
ORDER_THREE_ID = uuid.UUID("00000000-0000-4000-8000-000000000103")
ITEM_ONE_ID = uuid.UUID("00000000-0000-4000-8000-000000000201")
ITEM_TWO_ID = uuid.UUID("00000000-0000-4000-8000-000000000202")
ITEM_THREE_ID = uuid.UUID("00000000-0000-4000-8000-000000000203")


def seed_demo_data() -> None:
    """Insert stable fixture IDs with PostgreSQL conflict-safe inserts."""

    session_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()

    with SessionLocal.begin() as session:
        session.execute(
            insert(DemoUser)
            .values(
                id=DEMO_USER_ID,
                display_name="ReturnPilot Demo Customer",
                session_key_hash=session_hash,
            )
            .on_conflict_do_nothing(index_elements=[DemoUser.id])
        )

        orders = [
            {
                "id": ORDER_ONE_ID,
                "owner_id": DEMO_USER_ID,
                "external_order_ref": "RP-10001",
                "ordered_at": datetime(2026, 10, 10, tzinfo=UTC),
                "delivered_at": datetime(2026, 10, 12, tzinfo=UTC),
                "delivery_status": "delivered",
            },
            {
                "id": ORDER_TWO_ID,
                "owner_id": DEMO_USER_ID,
                "external_order_ref": "RP-10002",
                "ordered_at": datetime(2026, 10, 14, tzinfo=UTC),
                "delivered_at": None,
                "delivery_status": "in_transit",
            },
            {
                "id": ORDER_THREE_ID,
                "owner_id": DEMO_USER_ID,
                "external_order_ref": "RP-10003",
                "ordered_at": datetime(2026, 9, 20, tzinfo=UTC),
                "delivered_at": datetime(2026, 9, 23, tzinfo=UTC),
                "delivery_status": "delivered",
            },
        ]
        session.execute(insert(Order).values(orders).on_conflict_do_nothing(index_elements=[Order.id]))

        items = [
            {
                "id": ITEM_ONE_ID,
                "order_id": ORDER_ONE_ID,
                "sku": "RP-AUDIO-01",
                "product_name": "Auralux Wireless Headphones",
                "description": "Synthetic demo headphones, reported damaged on arrival.",
                "quantity": 1,
                "condition_code": "damaged",
            },
            {
                "id": ITEM_TWO_ID,
                "order_id": ORDER_TWO_ID,
                "sku": "RP-KITCHEN-02",
                "product_name": "Northline Electric Kettle",
                "description": "Synthetic demo order currently in transit.",
                "quantity": 1,
                "condition_code": "new",
            },
            {
                "id": ITEM_THREE_ID,
                "order_id": ORDER_THREE_ID,
                "sku": "RP-HOME-03",
                "product_name": "Harbor Desk Lamp",
                "description": "Synthetic demo order delivered earlier.",
                "quantity": 1,
                "condition_code": "new",
            },
        ]
        session.execute(
            insert(OrderItem).values(items).on_conflict_do_nothing(index_elements=[OrderItem.id])
        )


if __name__ == "__main__":
    seed_demo_data()
    print("Synthetic demo data seeded (existing rows were left unchanged).")
