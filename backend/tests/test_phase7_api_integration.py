"""API integration checks using the configured PostgreSQL DB and real MCP HTTP server."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import json
import urllib.error
import urllib.request
import uuid
from http.cookiejar import CookieJar
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.config import REPOSITORY_ROOT, get_settings
from app.database import SessionLocal
from app.main import app
from app.models import ApprovalRecord, AuditEvent, DemoUser, Order, OrderItem, ReturnProposal, ReturnRequest
from app.security import issue_approval_grant, sign_context, verify_context
from app.services import approve_from_grant, create_proposal
from app.seed import DEMO_USER_ID, ITEM_ONE_ID, ITEM_TWO_ID, ORDER_ONE_ID, ORDER_TWO_ID


@pytest.fixture(scope="module")
def real_mcp_server():
    """Launch the genuine MCP Streamable HTTP app on an ephemeral local port."""
    settings = get_settings()
    old_url = settings.mcp_server_url
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.mcp_server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "error",
        ],
        cwd=REPOSITORY_ROOT / "backend",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail("The local MCP server exited before becoming ready.")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                break
        except OSError:
            time.sleep(0.1)
    else:
        process.terminate()
        process.wait(timeout=5)
        pytest.fail("The local MCP server did not become ready.")

    settings.mcp_server_url = f"http://127.0.0.1:{port}/mcp"
    try:
        yield
    finally:
        settings.mcp_server_url = old_url
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.fixture
def demo_client(real_mcp_server):
    with TestClient(app) as client:
        response = client.post("/api/demo/session")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"
        yield client


def test_seeded_order_to_persisted_request_over_api_and_real_mcp(demo_client, request):
    client = demo_client

    search = client.get("/api/orders", params={"query": "RP-10001"})
    assert search.status_code == 200
    matches = search.json()["matches"]
    assert len(matches) == 1
    assert matches[0]["order_id"] == str(ORDER_ONE_ID)
    ambiguous = client.get("/api/orders", params={"query": "RP-1000"})
    unknown = client.get("/api/orders", params={"query": "RP-NOT-FOUND"})
    assert len(ambiguous.json()["matches"]) == 3
    assert unknown.json()["matches"] == []

    details = client.get(f"/api/orders/{ORDER_ONE_ID}")
    assert details.status_code == 200
    assert details.json()["items"][0]["order_item_id"] == str(ITEM_ONE_ID)

    eligibility = client.get(f"/api/orders/{ORDER_ONE_ID}/items/{ITEM_ONE_ID}/eligibility")
    assert eligibility.status_code == 200
    assert eligibility.json()["eligible"] is True

    ineligible = client.get(f"/api/orders/{ORDER_TWO_ID}/items/{ITEM_TWO_ID}/eligibility")
    assert ineligible.status_code == 200 and ineligible.json()["eligible"] is False
    rejected_proposal = client.post(
        "/api/proposals",
        json={"order_id": str(ORDER_TWO_ID), "order_item_id": str(ITEM_TWO_ID), "resolution": "replacement"},
    )
    assert rejected_proposal.status_code == 422

    declined_response = client.post(
        "/api/proposals",
        json={"order_id": str(ORDER_ONE_ID), "order_item_id": str(ITEM_ONE_ID), "resolution": "replacement"},
    )
    assert declined_response.status_code == 200
    declined_proposal = declined_response.json()
    declined_id = uuid.UUID(declined_proposal["proposal_id"])
    request.addfinalizer(lambda: cleanup_proposal(declined_id))
    declined = client.post(
        f"/api/proposals/{declined_proposal['proposal_id']}/decline",
        json={"snapshot_version": declined_proposal["snapshot_version"], "snapshot_hash": declined_proposal["snapshot_hash"]},
    )
    assert declined.status_code == 200 and declined.json()["state"] == "declined"
    with SessionLocal() as db:
        assert db.scalar(select(ReturnRequest).where(ReturnRequest.proposal_id == declined_id)) is None
        assert db.scalar(select(ApprovalRecord).where(ApprovalRecord.proposal_id == declined_id)).decision == "declined"

    # Extra browser fields are ignored; trusted owner and pending state come from the server.
    proposal_response = client.post(
        "/api/proposals",
        json={
            "order_id": str(ORDER_ONE_ID),
            "order_item_id": str(ITEM_ONE_ID),
            "resolution": "replacement",
            "owner_id": str(uuid.uuid4()),
            "state": "completed",
        },
    )
    assert proposal_response.status_code == 200
    proposal = proposal_response.json()
    proposal_id = uuid.UUID(str(proposal["proposal_id"]))

    def cleanup_business_records():
        with SessionLocal.begin() as db:
            db.execute(delete(AuditEvent).where(AuditEvent.proposal_id == proposal_id))
            db.execute(delete(ReturnRequest).where(ReturnRequest.proposal_id == proposal_id))
            db.execute(delete(ApprovalRecord).where(ApprovalRecord.proposal_id == proposal_id))
            db.execute(delete(ReturnProposal).where(ReturnProposal.id == proposal_id))

    request.addfinalizer(cleanup_business_records)
    assert proposal["owner_id"] == str(DEMO_USER_ID)
    assert proposal["state"] == "pending"

    with SessionLocal() as db:
        assert db.scalar(select(ReturnRequest).where(ReturnRequest.proposal_id == uuid.UUID(proposal["proposal_id"]))) is None
        assert db.scalar(select(ApprovalRecord).where(ApprovalRecord.proposal_id == uuid.UUID(proposal["proposal_id"]))) is None

    # The approve endpoint is the explicit decision; client state/owner fields do not authorize it.
    approved = client.post(
        f"/api/proposals/{proposal['proposal_id']}/approve",
        json={
            "snapshot_version": proposal["snapshot_version"],
            "snapshot_hash": proposal["snapshot_hash"],
            "owner_id": str(uuid.uuid4()),
            "state": "declined",
        },
    )
    assert approved.status_code == 200
    request_view = approved.json()
    assert request_view["outcome"] == "confirmed"
    assert request_view["proposal_id"] == proposal["proposal_id"]
    assert request_view["request_id"]

    with SessionLocal() as db:
        persisted_proposal = db.get(ReturnProposal, uuid.UUID(proposal["proposal_id"]))
        persisted_approval = db.scalar(select(ApprovalRecord).where(ApprovalRecord.proposal_id == persisted_proposal.id))
        persisted_request = db.scalar(select(ReturnRequest).where(ReturnRequest.proposal_id == persisted_proposal.id))
        events = set(db.scalars(select(AuditEvent.event_type).where(AuditEvent.proposal_id == persisted_proposal.id)).all())
        assert persisted_proposal.state == "completed"
        assert persisted_approval.decision == "approved"
        assert persisted_request.id == uuid.UUID(request_view["request_id"])
        assert persisted_request.approval_id == persisted_approval.id
        assert {"proposal_created", "approval_recorded", "request_created"} <= events

    status = client.get(f"/api/requests/{request_view['request_id']}")
    history = client.get(f"/api/requests/{request_view['request_id']}/history")
    assert status.status_code == history.status_code == 200
    assert status.json()["request_id"] == history.json()["request"]["request_id"] == request_view["request_id"]
    assert {event["event_type"] for event in history.json()["events"]} >= {
        "request_created",
        "request_status_checked",
    }


def test_api_rejects_missing_expired_and_foreign_sessions_and_owner_resources(demo_client):
    client = demo_client
    assert TestClient(app).get("/api/orders", params={"query": "RP-10001"}).status_code == 401

    expired = sign_context(
        {
            "typ": "demo_session",
            "user_id": str(DEMO_USER_ID),
            "iat": int(time.time()) - 20,
            "exp": int(time.time()) - 1,
            "nonce": "phase7-expired-session",
        }
    )
    with TestClient(app) as expired_client:
        expired_client.cookies.set(get_settings().demo_session_cookie, expired)
        assert expired_client.get("/api/orders", params={"query": "RP-10001"}).status_code == 401

    owner_id, order_id, item_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)
    foreign_request_id = None
    with SessionLocal.begin() as db:
        db.add(DemoUser(id=owner_id, display_name="Phase 7 isolation", session_key_hash=f"phase7-{owner_id}"))
        db.add(Order(id=order_id, owner_id=owner_id, external_order_ref=f"P7-{owner_id.hex[:10]}", ordered_at=now - timedelta(days=2), delivered_at=now - timedelta(days=1), delivery_status="delivered"))
        db.add(OrderItem(id=item_id, order_id=order_id, sku=f"P7-{owner_id.hex[:8]}", product_name="Synthetic isolation item", description="Test record", quantity=1, condition_code="damaged"))

    try:
        with SessionLocal() as db:
            proposal = create_proposal(db, owner_id, order_id, item_id, "replacement")
        claims = verify_context(issue_approval_grant(owner_id, proposal["proposal_id"], proposal["snapshot_version"], proposal["snapshot_hash"]), "approval")
        with SessionLocal() as db:
            foreign_request_id = approve_from_grant(db, owner_id, claims)["request_id"]

        assert client.get(f"/api/orders/{order_id}").status_code == 404
        assert client.get(f"/api/proposals/{proposal['proposal_id']}").status_code == 404
        decision_body = {"snapshot_version": proposal["snapshot_version"], "snapshot_hash": proposal["snapshot_hash"]}
        assert client.post(f"/api/proposals/{proposal['proposal_id']}/decline", json=decision_body).status_code == 404
        assert client.get(f"/api/requests/{foreign_request_id}").status_code == 404
        assert client.get(f"/api/requests/{foreign_request_id}/history").status_code == 404
    finally:
        with SessionLocal.begin() as db:
            db.execute(delete(AuditEvent).where(AuditEvent.owner_id == owner_id))
            db.execute(delete(ReturnRequest).where(ReturnRequest.owner_id == owner_id))
            db.execute(delete(ApprovalRecord).where(ApprovalRecord.owner_id == owner_id))
            db.execute(delete(ReturnProposal).where(ReturnProposal.owner_id == owner_id))
            db.execute(delete(OrderItem).where(OrderItem.order_id == order_id))
            db.execute(delete(Order).where(Order.id == order_id))
            db.execute(delete(DemoUser).where(DemoUser.id == owner_id))


def test_request_status_and_history_survive_api_process_restart(real_mcp_server, request):
    with TestClient(app) as workflow_client:
        session = workflow_client.post("/api/demo/session")
        assert session.status_code == 200
        proposal_response = workflow_client.post(
            "/api/proposals",
            json={"order_id": str(ORDER_ONE_ID), "order_item_id": str(ITEM_ONE_ID), "resolution": "replacement"},
        )
        assert proposal_response.status_code == 200
        proposal = proposal_response.json()
        approved = workflow_client.post(
            f"/api/proposals/{proposal['proposal_id']}/approve",
            json={"snapshot_version": proposal["snapshot_version"], "snapshot_hash": proposal["snapshot_hash"]},
        )
        assert approved.status_code == 200
        request_view = approved.json()
        assert request_view["outcome"] == "confirmed"

    proposal_id = uuid.UUID(proposal["proposal_id"])
    request_id = request_view["request_id"]
    request.addfinalizer(lambda: cleanup_proposal(proposal_id))

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    def start_api():
        import os

        child_env = os.environ.copy()
        child_env["MCP_SERVER_URL"] = get_settings().mcp_server_url
        return subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
            cwd=REPOSITORY_ROOT / "backend",
            env=child_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop_api(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    process = None
    cookie_jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

    def call(path: str, method: str = "GET"):
        request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
        with opener.open(request, timeout=5) as response:
            return response.status, json.loads(response.read())

    try:
        for restart in range(2):
            process = start_api()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    pytest.fail("FastAPI exited before becoming ready.")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as health:
                        if health.status == 200:
                            break
                except (OSError, urllib.error.URLError):
                    time.sleep(0.1)
            else:
                pytest.fail("FastAPI did not become ready.")

            if restart == 0:
                status, session = call("/api/demo/session", "POST")
                assert status == 200 and session["status"] == "ready"
                status, persisted = call(f"/api/requests/{request_id}")
                assert status == 200 and persisted["request_id"] == request_id
                stop_api(process)
                process = None
            else:
                status, history = call(f"/api/requests/{request_id}/history")
                assert status == 200
                assert history["request"]["request_id"] == request_id
                assert "request_created" in {event["event_type"] for event in history["events"]}
                with SessionLocal() as db:
                    assert db.get(ReturnProposal, proposal_id).state == "completed"
                    assert db.scalar(select(ReturnRequest).where(ReturnRequest.id == uuid.UUID(request_id))) is not None
                stop_api(process)
                process = None
    finally:
        if process is not None:
            stop_api(process)
def cleanup_proposal(proposal_id: uuid.UUID) -> None:
    with SessionLocal.begin() as db:
        db.execute(delete(AuditEvent).where(AuditEvent.proposal_id == proposal_id))
        db.execute(delete(ReturnRequest).where(ReturnRequest.proposal_id == proposal_id))
        db.execute(delete(ApprovalRecord).where(ApprovalRecord.proposal_id == proposal_id))
        db.execute(delete(ReturnProposal).where(ReturnProposal.id == proposal_id))
