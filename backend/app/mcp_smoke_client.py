"""Connect to the local MCP server and verify negotiation, schema, and tool calls."""

from __future__ import annotations

import asyncio
import sys

import httpx2

from app.config import get_settings
from app.mcp_client import open_authenticated_mcp_client


def _is_transport_unavailable(error: BaseException) -> bool:
    if isinstance(error, (httpx2.HTTPError, OSError, TimeoutError)):
        return True
    if isinstance(error, BaseExceptionGroup):
        return any(_is_transport_unavailable(child) for child in error.exceptions)
    return False


async def run_smoke_check() -> int:
    settings = get_settings()
    try:
        async with open_authenticated_mcp_client() as client:
            version = client.protocol_version
            print(f"protocol_version={version}")
            if version != "2025-11-25":
                print("FAIL: expected initialize negotiation for protocol 2025-11-25", file=sys.stderr)
                return 1

            listing = await client.list_tools()
            discovered = {item.name for item in listing.tools}
            required_business_tools = {
                "find_order",
                "get_order_details",
                "check_return_eligibility",
                "create_return_request",
                "get_return_status",
            }
            missing_tools = required_business_tools - discovered
            if missing_tools:
                print(f"FAIL: missing business tools: {sorted(missing_tools)}", file=sys.stderr)
                return 1
            print(f"discovered_business_tools={sorted(required_business_tools)}")
            create_tool = next(item for item in listing.tools if item.name == "create_return_request")
            if "approval_grant" in create_tool.input_schema.get("properties", {}):
                print("FAIL: approval grants must not be exposed as MCP tool arguments", file=sys.stderr)
                return 1
            print("create_return_request_grant_argument=absent")
            tool = next((item for item in listing.tools if item.name == "server_status"), None)
            if tool is None:
                print("FAIL: server_status tool was not discovered", file=sys.stderr)
                return 1
            print(f"discovered_tool={tool.name}")
            print(f"input_schema={tool.input_schema}")
            print(f"output_schema={tool.output_schema}")

            result = await client.call_tool("server_status", {"component": "mcp"})
            if result.is_error or result.structured_content != {
                "status": "ok",
                "service": "returnpilot-mcp",
            }:
                print("FAIL: server_status returned an invalid structured result", file=sys.stderr)
                return 1
            print(f"tool_invocation=OK structured_content={result.structured_content}")

            invalid_result = await client.call_tool("server_status", {"component": "unexpected"})
            if not invalid_result.is_error:
                print("FAIL: invalid tool input was not returned as a tool error", file=sys.stderr)
                return 1
            print("invalid_input=structured_tool_error")
            return 0
    except Exception as exc:
        if not _is_transport_unavailable(exc):
            raise
        print(f"FAIL: MCP server unavailable at {settings.mcp_server_url}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_smoke_check()))
