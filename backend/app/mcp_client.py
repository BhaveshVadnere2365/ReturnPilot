"""Authenticated MCP client construction shared by backend callers and smoke checks."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app.config import get_settings
from app.security import issue_actor_context


@asynccontextmanager
async def open_authenticated_mcp_client(actor_id=None, approval_grant: str | None = None) -> AsyncIterator[Client]:
    """Open MCP with server credential and signed server-only caller/approval context."""

    settings = get_settings()
    secret = (
        settings.mcp_shared_secret.get_secret_value()
        if settings.mcp_shared_secret is not None
        else ""
    )
    if not secret:
        raise RuntimeError("Set a non-empty MCP_SHARED_SECRET for backend MCP calls.")

    timeout = httpx2.Timeout(30.0, read=300.0)
    headers = {"Authorization": f"Bearer {secret}"}
    if actor_id is not None:
        headers["X-ReturnPilot-Actor"] = issue_actor_context(actor_id)
    if approval_grant is not None:
        headers["X-ReturnPilot-Approval-Grant"] = approval_grant
    async with httpx2.AsyncClient(
        headers=headers,
        timeout=timeout,
    ) as http_client:
        transport = streamable_http_client(
            settings.mcp_server_url,
            http_client=http_client,
        )
        async with Client(transport, mode="legacy") as client:
            yield client
