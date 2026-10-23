# ReturnPilot — Synthetic Returns Support Demo

This repository contains the synthetic-data-only ReturnPilot React/Vite customer workspace and PostgreSQL-backed FastAPI/MCP workflow services. PostgreSQL is the durable database; SQLite is not supported. All return requests are simulated and no physical replacement is shipped.

## Local setup (PowerShell)

1. Install Python 3.12+ and Node.js 22.12+ (Vite 8 requires Node 20.19+ or 22.12+), and start PostgreSQL.
2. Create a local PostgreSQL role and database using your PostgreSQL administrator, for example:

   ```sql
   CREATE ROLE returnpilot LOGIN PASSWORD 'set-a-local-password';
   CREATE DATABASE returnpilot OWNER returnpilot;
   ```

3. From the repository root, create the local environment file and set the database URL:

   ```powershell
   Copy-Item .env.example .env
   # Edit .env and replace the local PostgreSQL username/password as needed.
   ```

   Set strong, random server-only values for `GRANT_SIGNING_SECRET` and `MCP_SHARED_SECRET`. Both backend processes read them from `.env`; never place them in frontend configuration, tool prompts, or commit `.env`.

4. Create the Python environment and install the backend:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -e "backend[dev]"
   ```

5. Apply the PostgreSQL schema and seed synthetic demo data (safe to repeat):

   ```powershell
   .\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
   Set-Location backend
   ..\.venv\Scripts\python.exe -m app.seed
   Set-Location ..
   ```

6. Start the API in one terminal and the frontend in another:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
   ```

   ```powershell
   Set-Location frontend
   npm ci
   npm run dev
   ```

The API health endpoint is `http://127.0.0.1:8000/health`; it reports database connectivity. Vite prints the frontend URL, normally `http://localhost:5173`. The Vite development server proxies `/api` to `http://127.0.0.1:8000` by default. Set `VITE_API_PROXY_TARGET` to change the development proxy target, or `VITE_API_BASE_URL` when serving the frontend separately. The browser uses the signed HTTP-only demo-session cookie with credentialed requests; no session token or server secret is stored in browser storage.

The workspace renders order, eligibility, proposal, approval, request, and activity information from backend responses. It does not make eligibility or authorization decisions. If Gemini is unavailable, the UI shows the backend's safe error and lets the user retry; it does not present a failed turn as a successful conversation. Request history can be looked up using the persisted request ID returned by approval.

## Phase 3 MCP server and smoke test

The MCP endpoint uses the official Python MCP SDK, pinned to `mcp==2.3.0`. The SDK supports Streamable HTTP and prior MCP protocol revisions; the smoke client selects its legacy handshake mode to negotiate the architecture's required `2025-11-25` version. It uses the SDK's `MCPServer` and `Client` APIs over the real `/mcp` Streamable HTTP endpoint. See the [official SDK release](https://pypi.org/project/mcp/2.3.0/) and [protocol-version documentation](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/protocol-versions.md).

After installing backend dependencies, set a strong random `MCP_SHARED_SECRET` in the ignored `.env` file. It must be available to both backend processes and must never be added to frontend settings or model prompts. `MCP_SERVER_URL` defaults to `http://127.0.0.1:8001/mcp`.

Start the MCP server in one PowerShell terminal:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m uvicorn app.mcp_server:app --host 127.0.0.1 --port 8001
```

Run the genuine SDK client smoke check from another terminal:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m app.mcp_smoke_client
```

The client reports the negotiated protocol version, discovers the `server_status` input/output schemas, checks a successful structured result, and verifies that invalid tool input returns an MCP tool error. It prints a clear unavailable message when the MCP server cannot be reached. Requests without the shared Bearer credential receive HTTP 401. FastAPI also supplies a short-lived signed actor context for business calls; MCP business tools reject calls without that context.

## Phase 4 backend workflow

The demo session endpoint issues an HTTP-only, SameSite=Strict cookie for the one synthetic demo user:

```powershell
Invoke-WebRequest -Method Post http://127.0.0.1:8000/api/demo/session -SessionVariable rp
```

Authenticated API routes use that server-validated cookie; callers cannot choose an owner ID. The API exposes order search/details, item eligibility, proposal create/retrieval, explicit approve/decline, and request status/history under `/api`. Proposal responses include the exact snapshot, version, and SHA-256 digest required for a decision. Approval sends those displayed snapshot identifiers to FastAPI.

Only the explicit FastAPI approval endpoint creates a short-lived HMAC-SHA-256 approval grant. It invokes `create_return_request` through the genuine authenticated MCP Streamable HTTP client and sends the grant in a server-only HTTP header; the tool has no grant argument. The grant is not returned to the browser, included in tool schemas, or sent to an LLM. MCP verifies both the backend caller and grant; the shared service rechecks ownership, proposal state/expiry, current eligibility, and persisted snapshot integrity before performing the atomic PostgreSQL approval, request, completion, and audit transaction.

If the MCP response or database commit cannot be confirmed, the API returns an unconfirmed status. Reconcile through `GET /api/proposals/{proposal_id}` or request status before retrying; the API never claims success without a persisted request. The service uses proposal ID and the unique request constraint for idempotency. Synthetic policy eligibility is limited to delivered, damaged items within 30 days of order date; all requests are simulated and no physical replacement is shipped.

Run the PostgreSQL-backed Phase 4 tests from `backend`:

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_phase4_postgres.py -p no:cacheprovider
```

## Phase 5 Gemini conversation API

The authenticated `POST /api/conversation` endpoint accepts `{"message":"..."}` using the existing signed demo-session cookie. Configure `GEMINI_API_KEY` only in the repository-root `.env`; the backend reads it with server-side settings. `GEMINI_MODEL` defaults to `gemini-3.5-flash-lite`, and `GEMINI_MAX_ITERATIONS` defaults to 4 (maximum 8). Calls have a 20-second provider timeout and one SDK attempt; rate limits are returned as a safe retry-later response. Do not put the key in Vite variables, tool arguments, prompts, logs, or fixtures.

The implementation pins Google's official `google-genai==2.31.0` SDK. `gemini-3.5-flash-lite` is a stable function-calling Flash-Lite model documented by Google and selected for the constrained demo workload. Google's published standard paid pricing currently lists $0.30 per million input tokens and $2.50 per million output tokens; free-tier availability, quotas, model access, and pricing can change by account and date. See [Google's model list](https://ai.google.dev/gemini-api/docs/models), [function calling guide](https://ai.google.dev/gemini-api/docs/generate-content/function-calling), and [pricing](https://ai.google.dev/gemini-api/docs/pricing.md).

Gemini can request only `find_order`, `get_order_details`, and `check_return_eligibility` through the existing authenticated MCP Streamable HTTP client. FastAPI validates every function name and argument and supplies the owner from the signed session. The model does not receive or initiate `create_return_request`, approval grants, or authorization context. Final replies are deterministic templates grounded in structured tool results. A proposal is created only by the shared service when the user explicitly requests a replacement, a unique order/item is identified, and the matching eligibility check is positive. The user must still approve the proposal through the existing explicit approval endpoint.

If `GEMINI_API_KEY` is missing or empty, the conversation endpoint returns a safe `provider_not_configured` response. The endpoint can be exercised with a demo cookie after starting the API and MCP server; provider-mocked tests do not require a Google key:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests/test_phase5_conversation.py -p no:cacheprovider
```

## Phase 7 integration verification

With PostgreSQL migrated and synthetic records seeded, run the backend suite from `backend`:

```powershell
..\.venv\Scripts\python.exe -m pytest tests -p no:cacheprovider -q
```

The Phase 7 API integration tests use PostgreSQL and start the genuine MCP Streamable HTTP server. They verify the seeded-order API flow, explicit approval through MCP, ownership/session boundaries, and request history across a FastAPI process restart. They remove the proposal and request records they create. Run the frontend checks from `frontend` with `npm test` and `npm run build`. Gemini behavior is covered with mocked-provider tests; the suite does not make live Gemini requests.
