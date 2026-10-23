"""Typed API and MCP data contracts for the deterministic workflow."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class OrderMatch(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    order_id: uuid.UUID
    external_order_ref: str
    ordered_at: datetime
    delivered_at: datetime | None
    delivery_status: str
    items: list[dict[str, Any]]


class EligibilityResult(BaseModel):
    eligible: bool
    reasons: list[str]
    policy_version: str = "demo-1"


class ProposalCreate(BaseModel):
    order_id: uuid.UUID
    order_item_id: uuid.UUID
    resolution: Literal["replacement"]


class ProposalView(BaseModel):
    proposal_id: uuid.UUID
    owner_id: uuid.UUID
    order_id: uuid.UUID
    order_item_id: uuid.UUID
    resolution: str
    state: str
    action_snapshot: dict[str, Any]
    snapshot_version: int
    snapshot_hash: str
    policy_result: dict[str, Any]
    expires_at: datetime | None
    request: "RequestView | None" = None


class DecisionInput(BaseModel):
    snapshot_version: int = Field(ge=1)
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class RequestView(BaseModel):
    request_id: uuid.UUID
    proposal_id: uuid.UUID
    status: str
    created_at: datetime
    outcome: Literal["confirmed"] = "confirmed"


class UnconfirmedView(BaseModel):
    proposal_id: uuid.UUID
    status: Literal["unconfirmed"] = "unconfirmed"
    message: Literal["Outcome not yet confirmed. Check request status before retrying."] = (
        "Outcome not yet confirmed. Check request status before retrying."
    )


class DeclineView(BaseModel):
    proposal_id: uuid.UUID
    state: Literal["declined"] = "declined"
    decision: Literal["declined"] = "declined"


class RequestHistory(BaseModel):
    request: RequestView
    events: list[dict[str, Any]]


class ErrorView(BaseModel):
    code: str
    message: str
