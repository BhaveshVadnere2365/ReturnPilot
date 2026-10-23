# ReturnPilot

**Synthetic return support with a reviewable approval boundary.** ReturnPilot is a conversational demo for finding an order, checking a deterministic replacement policy, and preparing a simulated request for a person to approve.

It brings together a React workspace, a FastAPI service, Gemini function calling, a genuine MCP Streamable HTTP server, shared Python domain services, and PostgreSQL. It uses synthetic records only: it does not connect to real Amazon accounts or retailer systems, and it cannot issue refunds, ship replacements, or generate return labels.

## Contents

- [Project overview](#project-overview)
- [Features](#features)
- [How it works](#how-it-works)
- [Architecture](#architecture)
- [Technology](#technology)
- [Security and reliability](#security-and-reliability)
- [Prerequisites](#prerequisites)
- [Installation and setup](#installation-and-setup)
- [Using the demo](#using-the-demo)
- [API and MCP reference](#api-and-mcp-reference)
- [Testing and verification](#testing-and-verification)
- [Limitations and scope](#limitations-and-scope)
- [Roadmap](#roadmap)
- [Hackathon context](#hackathon-context)
- [License](#license)

## Project overview

Return and replacement support often requires a customer to identify an order, explain an issue, check policy rules, and confirm the proposed action. ReturnPilot demonstrates that flow with synthetic commerce data and a conversational interface.

Gemini can select from a small allowlist of read/check tools. FastAPI validates tool names and arguments and calls the authenticated MCP client. Deterministic shared services perform order lookup, ownership checks, eligibility evaluation, proposal creation, and request operations. PostgreSQL stores the durable business state. The model cannot approve a proposal or invoke request creation.

The technical focus is the boundary between assistance and action: proposals capture a versioned action snapshot; approval is explicit; the server revalidates the proposal before one atomic PostgreSQL transaction records approval, creates the simulated request, completes the proposal, and writes related audit events.

## Features

- Search synthetic orders by reference, product, or SKU, and retrieve their item details.
- Apply a deterministic replacement policy: the order must be delivered, the item must be marked damaged, and the order date must be within the 30-day demo window.
- Present a pending proposal containing the action snapshot, version, hash, and conditions. Creating a proposal does not create a request.
- Approve or decline explicitly through the authenticated workspace.
- Create the simulated request only through the trusted FastAPI-to-MCP approval flow.
- Retrieve persisted request status and history, including allowlisted audit events.
- Isolate demo data by the authenticated server-side demo identity; clients and the model cannot choose the owner.
- Protect against duplicate request creation and reconcile outcomes that cannot immediately be confirmed.
- Show order, proposal, request, and activity information from structured backend responses.

## How it works

1. Opening the workspace starts a synthetic demo session. FastAPI issues a signed, HTTP-only cookie; the browser sends it with authenticated API calls.
2. The customer searches directly or asks the assistant about an order. When Gemini is available, it may request an allowlisted lookup or eligibility check. The backend validates and executes those calls through MCP.
3. The shared service evaluates policy and verifies ownership. If the customer clearly requests a replacement, the relevant item is unambiguous, and eligibility is positive, the service can create a **pending proposal**. No request exists yet.
4. The UI displays the persisted proposal snapshot and asks the customer to approve or decline. The snapshot version and hash identify the proposal data presented by the UI; they are not credentials.
5. On explicit approval, FastAPI issues a short-lived, server-signed grant and calls the MCP `create_return_request` tool. MCP authenticates the backend caller and verifies the grant. The shared service independently checks actor, ownership, state, expiry, current eligibility, and snapshot integrity before committing the approval, request, completed proposal, and related audit events atomically.
6. The UI reports success only after the backend confirms persistence. If the outcome is unknown, the UI remains neutral while the backend reconciles by proposal and request relationship; no blind retry creates another request. The customer can look up the persisted request and its history.

The frontend presents results and collects the decision; it does not determine eligibility or authorize an action. The model supplies neither authorization nor trusted identity.

## Architecture

```mermaid
flowchart LR
    Customer[Customer]
    UI[React and Vite workspace]
    API[FastAPI API and bounded orchestrator]
    Gemini[Gemini API]
    Client[Python MCP client]
    MCP[Python MCP server<br/>Streamable HTTP]
    Services[Shared Python domain services]
    DB[(PostgreSQL)]

    Customer --> UI
    UI -->|Session cookie and API requests| API
    API <-->|Server-side function calling| Gemini
    API -->|Validated read and check calls| Client
    Client -->|Authenticated MCP protocol| MCP
    MCP --> Services
    API --> Services
    Services --> DB
    UI -->|Explicit approval with displayed snapshot identifiers| API
    API -->|Server-signed approval grant| Client
    Client -->|Consequential tool call after approval| MCP
```

The consequential call is initiated by the authenticated FastAPI approval route. The grant is carried in server-side MCP request context, not exposed as a tool argument, prompt value, or browser response. Gemini can request only `find_order`, `get_order_details`, and `check_return_eligibility`.

## Technology

| Area | Implementation |
|---|---|
| Frontend | JavaScript, React 19, Vite 8 |
| API and domain | Python 3.12+, FastAPI, Pydantic 2 |
| Conversational provider | Google `google-genai` SDK; configured model defaults to `gemini-3.5-flash-lite` |
| Tool transport | Python MCP SDK `mcp==2.3.0`, Streamable HTTP; smoke client expects protocol version `2025-11-25` |
| Persistence | PostgreSQL, SQLAlchemy 2, Alembic |
| Tests | pytest; Vitest, Testing Library, and jsdom |

Dependency versions are pinned in [backend/pyproject.toml](backend/pyproject.toml), [frontend/package.json](frontend/package.json), and [frontend/package-lock.json](frontend/package-lock.json).

## Security and reliability

- FastAPI resolves the actor from a signed demo-session cookie. Owner identity is supplied to shared services from this trusted context, not accepted from browser or model arguments.
- MCP business tools require authenticated backend context. Request creation additionally requires a valid, short-lived HMAC-SHA-256 grant bound to the actor, proposal, approved action, snapshot version and hash, and expiry.
- Approval revalidates the persisted snapshot and independently checks ownership, pending state, expiry, and current eligibility. Hash comparison detects a stale or mismatched snapshot; it does not prove what a person saw or replace those checks.
- Approval record, request, proposal completion, and related audit events use one PostgreSQL transaction. Database constraints and proposal-row locking protect against duplicate submissions and concurrent approvals.
- If commit status cannot be established, the API reports an unconfirmed outcome. It reconciles against persisted proposal/request state before returning success; uncertainty is not represented as a guaranteed durable database state.
- Audit details use an allowlist and exclude secrets, grants, raw session tokens, full snapshots, and model chain-of-thought. The event types are `proposal_created`, `approval_recorded`, `request_created`, `proposal_declined`, `proposal_expired`, and `request_status_checked`.

These controls describe the local synthetic demo. They are not a claim that ReturnPilot is production-ready or a substitute for a production identity, threat, privacy, and operational review.

## Prerequisites

- Python **3.12 or newer** (`requires-python` in `backend/pyproject.toml`).
- Node.js **20.19 or newer in the 20.x line, or 22.12 or newer** for the locked Vite 8 toolchain (from the Vite package engine range). The repository does not pin an npm version; use an npm release that supports lockfile version 3.
- A reachable PostgreSQL database. The repository requires PostgreSQL and does not declare a minimum server version.
- A Gemini API key is optional for starting the app, but required for live Gemini conversation requests. Provider access, quotas, and model availability depend on the Google account and are not guaranteed by this project.
- PowerShell on Windows, or a POSIX shell on Linux/macOS.

## Installation and setup

Clone the repository from your Git host, then run the commands from the repository root unless a step changes directory. No repository URL is embedded here because one was not supplied.

### Windows PowerShell

1. Start PostgreSQL and create a local role and database. For example, connect with your PostgreSQL administrator:

   ```powershell
   psql -U postgres
   ```

   Then enter SQL in the `psql` prompt, replacing the placeholder password locally:

   ```sql
   CREATE ROLE returnpilot LOGIN PASSWORD 'replace-this-local-password';
   CREATE DATABASE returnpilot OWNER returnpilot;
   ```

2. Create the local environment file, edit it, and set the database URL and server-only secrets:

   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```

   Replace the example database password. Set a random `GRANT_SIGNING_SECRET` of at least 32 bytes and a non-empty random `MCP_SHARED_SECRET`. Add `GEMINI_API_KEY` if you want to test live conversation. Never commit `.env` or put these values in frontend configuration.

3. Create the Python environment and install the pinned backend package and test dependency:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -e "backend[dev]"
   ```

4. Apply the migration and seed the synthetic demo records. Seeding uses stable IDs and conflict-safe inserts, so rerunning it does not duplicate those rows:

   ```powershell
   .\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
   Set-Location backend
   ..\.venv\Scripts\python.exe -m app.seed
   Set-Location ..
   ```

5. Start each service in its own terminal, from the repository root for FastAPI and Vite, and from `backend` for MCP.

   **Terminal 1 — FastAPI, repository root:**

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
   ```

   **Terminal 2 — MCP server:**

   ```powershell
   Set-Location backend
   ..\.venv\Scripts\python.exe -m uvicorn app.mcp_server:app --host 127.0.0.1 --port 8001
   ```

   **Terminal 3 — frontend:**

   ```powershell
   Set-Location frontend
   npm ci
   npm run dev
   ```

   Vite prints its local URL, normally `http://localhost:5173`. Its development server proxies `/api` to `http://127.0.0.1:8000` by default. `VITE_API_PROXY_TARGET` changes that proxy target; `VITE_API_BASE_URL` sets the API base URL when serving the frontend separately.

### Linux and macOS

Use the same PostgreSQL setup and `.env` values above, then run from the repository root:

```bash
psql -U postgres
# In the psql prompt, run the SQL below with a local password placeholder replaced.
```

```sql
CREATE ROLE returnpilot LOGIN PASSWORD 'replace-this-local-password';
CREATE DATABASE returnpilot OWNER returnpilot;
```

```bash
cp .env.example .env
# Edit .env locally; do not copy secrets into source files.
python3 -m venv .venv
./.venv/bin/python -m pip install -e 'backend[dev]'
./.venv/bin/python -m alembic -c backend/alembic.ini upgrade head
(cd backend && ../.venv/bin/python -m app.seed)
```

Start separate terminal processes:

```bash
# Repository root: FastAPI
./.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

```bash
# backend directory: MCP server
cd backend
../.venv/bin/python -m uvicorn app.mcp_server:app --host 127.0.0.1 --port 8001
```

```bash
# frontend directory: Vite
cd frontend
npm ci
npm run dev
```

The API health check is `http://127.0.0.1:8000/health`; a healthy response reports `{"status":"ok","database":"connected"}`. The MCP endpoint is `http://127.0.0.1:8001/mcp` and is authenticated; opening it in a browser without backend credentials is expected to return unauthorized.

## Configuration

Settings are loaded by the backend from the repository-root `.env` file and environment variables. `.env.example` is a credential-free template; its database password is a placeholder. Do not use the placeholder in a real local connection.

| Variable | Required | Default or purpose |
|---|---:|---|
| `DATABASE_URL` | Yes for database operations | SQLAlchemy URL; example format is `postgresql+psycopg://user:password@localhost:5432/returnpilot`. Default is a local placeholder. |
| `MCP_SHARED_SECRET` | Yes to start/use MCP | Shared server-side credential for FastAPI-to-MCP calls. Must be non-empty. |
| `GRANT_SIGNING_SECRET` | Yes for signed demo sessions and approval grants | Server-side HMAC signing key; at least 32 bytes. |
| `MCP_SERVER_URL` | No | MCP endpoint; defaults to `http://127.0.0.1:8001/mcp`. |
| `GEMINI_API_KEY` | No to start; required for live conversation | Server-side Google Gemini API key. Without it, conversation returns a safe unavailable response. |
| `GEMINI_MODEL` | No | Defaults to `gemini-3.5-flash-lite`. |
| `GEMINI_MAX_ITERATIONS` | No | Defaults to 4; the backend accepts values from 1 to 8. |
| `GEMINI_TIMEOUT_SECONDS` | No | Defaults to 20 seconds. |
| `DEMO_SESSION_COOKIE` | No | Cookie name; defaults to `returnpilot_demo_session`. |
| `DEMO_SESSION_TTL_SECONDS` | No | Session lifetime; defaults to 12 hours. |

The last two settings are supported by the backend but are not included in `.env.example`. Keep all provider credentials and signing/shared secrets server-side. Do not use `VITE_` variables for secrets; Vite variables can be exposed to browser code.

## Using the demo

The frontend starts a demo session when opened. The signed cookie is held by the browser and sent automatically with API requests. You can also establish an in-memory PowerShell web session and search the seeded order without printing or manually handling its cookie:

```powershell
$rp = [Microsoft.PowerShell.Commands.WebRequestSession]::new()
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/demo/session -WebSession $rp
$orders = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/orders?query=RP-10001' -WebSession $rp
$orders.matches[0].items
```

Seeded examples from [backend/app/seed.py](backend/app/seed.py):

| Order reference | Item | Seeded context |
|---|---|---|
| `RP-10001` | Auralux Wireless Headphones (`RP-AUDIO-01`) | Delivered; marked damaged. It meets the current demo policy while within the 30-day window. |
| `RP-10002` | Northline Electric Kettle (`RP-KITCHEN-02`) | In transit; not currently eligible. |
| `RP-10003` | Harbor Desk Lamp (`RP-HOME-03`) | Delivered and not marked damaged; it does not meet the current demo policy. |

Example conversation prompts:

- “Find order RP-10001.”
- “Check replacement eligibility for the damaged headphones in RP-10001.”
- “I want a replacement for this damaged item.”
- “Find my kettle order and tell me whether it is eligible.”

The assistant may ask you to clarify an order or item. A clear replacement request can prepare a proposal only after the order/item is identified and a positive eligibility result is returned. Review the snapshot and use **Approve** or **Decline** in the workspace. Declining does not create a request. Approval returns a persisted request ID when confirmed; use the Request history view to see its status and recorded activity. If the outcome is unconfirmed, check the proposal/request state before retrying.

## API and MCP reference

All `/api` routes below require the demo-session cookie unless indicated. The owner is resolved server-side; requests do not accept an owner ID.

| Method and route | Purpose |
|---|---|
| `GET /health` | Database connectivity check; no demo session required. |
| `POST /api/demo/session` | Start the seeded demo session and set the HTTP-only cookie. |
| `POST /api/conversation` | Accepts `{"message":"..."}`; returns `status`, `reply`, `tool_events`, and an optional proposal. |
| `GET /api/orders?query=...` | Search the current user's synthetic orders. |
| `GET /api/orders/{order_id}` | Retrieve an owned order and its items. |
| `GET /api/orders/{order_id}/items/{item_id}/eligibility` | Run the deterministic policy check. |
| `POST /api/proposals` | Create a pending proposal from `order_id`, `order_item_id`, and `resolution: "replacement"`; does not create a request. |
| `GET /api/proposals/{proposal_id}` | Retrieve the owner's proposal, snapshot identifiers, state, and any associated request. Also used to reconcile an uncertain outcome. |
| `POST /api/proposals/{proposal_id}/approve` | Requires `snapshot_version` and `snapshot_hash` from the displayed proposal. Returns a confirmed request or an unconfirmed outcome. |
| `POST /api/proposals/{proposal_id}/decline` | Requires the same snapshot fields; records a decline without creating a request. |
| `GET /api/requests/{request_id}` | Retrieve an owned request's persisted status. |
| `GET /api/requests/{request_id}/history` | Retrieve persisted request status and associated audit events. |

Domain/API failures use structured errors with a code and safe message. An approval response is successful only when it contains a confirmed persisted request; an unconfirmed response is not success.

### MCP

The separate Python MCP server exposes genuine MCP Streamable HTTP at `/mcp`. It requires the server-side shared credential; business tools also require trusted actor context. Available tools are:

| Tool | Inputs | Purpose and boundary |
|---|---|---|
| `server_status` | `component: "mcp"` | Report MCP process status without accessing business data. |
| `find_order` | `query` | Search orders for the trusted actor. |
| `get_order_details` | `order_id` | Retrieve an owned order. |
| `check_return_eligibility` | `order_id`, `order_item_id` | Evaluate policy for an owned item. |
| `create_return_request` | No tool arguments | Consequential operation; succeeds only when invoked through the trusted explicit-approval path with a verified server-side grant. It is not exposed to Gemini. |
| `get_return_status` | `request_id` | Retrieve an owned request's status. |

The browser does not call MCP directly. The approval grant and private authentication context are not part of public request schemas or tool arguments.

## Testing and verification

With the development dependencies installed, run from `backend`:

```powershell
..\.venv\Scripts\python.exe -m pytest tests -p no:cacheprovider -q
```

The full backend suite includes PostgreSQL integration tests and requires the configured database. It covers PostgreSQL constraints and transactions, isolated fixture ownership, approval/grant validation and replay, uncertain outcomes, API/MCP integration, and mocked Gemini behavior. The suite does not make live Gemini requests. Phase 7 tests start a real local MCP Streamable HTTP server and clean up their disposable business fixtures. The Phase 5 conversation tests mock Gemini and do not need a provider key.

Run frontend tests and the production build from `frontend`:

```powershell
npm test
npm run build
```

For Linux/macOS, use the same commands with the local environment's Python executable, for example `../.venv/bin/python -m pytest tests -p no:cacheprovider -q` from `backend`.

Check the API and migration from the repository root:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini current
```

For the genuine MCP transport smoke check, keep the MCP server running and run from `backend`:

```powershell
..\.venv\Scripts\python.exe -m app.mcp_smoke_client
```

The smoke client checks protocol negotiation, tool discovery, structured status invocation, and invalid-input handling. It does not call Gemini or create a request.

## Limitations and scope

- All order and request data is synthetic. ReturnPilot does not connect to real Amazon ordering systems or private retailer APIs.
- Requests are database records for a simulation. No refund, replacement shipment, return label, or physical return is executed.
- The demo identity is a single seeded customer, not a production account system. There is no registration, real customer authentication, or retailer identity federation.
- The local demo cookie is configured for local HTTP development; deployment would require TLS and production cookie/security configuration.
- Gemini requires a configured API key and provider access. The model's availability and quota are external dependencies; the application returns a safe error when the provider is unavailable.
- The conversational UI is text-based. Alexa voice integration and an Alexa skill are not implemented.
- The project is a local hackathon/demo implementation, not production-ready commerce software.

## Roadmap

Potential future work, not implemented in this repository:

- Add broader policy and lifecycle scenarios with additional synthetic fixtures.
- Improve operational observability and deployment/security reviews.
- Evaluate a voice interface or Alexa integration separately, without weakening explicit approval.
- Consider retailer integration only with authorized APIs, appropriate credentials, and a separately approved scope.

## Hackathon context

ReturnPilot was designed as a synthetic customer-support demonstration relevant to the Amazon Developer Hackathon 2026 Alexa+ / MCP track. The implementation includes a genuine MCP Streamable HTTP server and server-side tool orchestration. It does **not** implement Alexa voice or Alexa+ integration, and it is not affiliated with, endorsed by, or connected to Amazon or any retailer.

## License

No license file is present in this repository. A license has not been selected; licensing should be decided separately before granting reuse rights.
