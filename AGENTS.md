# Codex Project Instructions

## Purpose and approved stack

ReturnPilot is a synthetic-data customer return/replacement workflow for the Amazon Developer Hackathon 2026 Alexa+ track. Approved MVP stack: React/Vite/JavaScript, Python/FastAPI/Pydantic, server-side LLM tool calling, MCP client and a real Python MCP Streamable HTTP server, PostgreSQL, SQLAlchemy, Alembic, pytest, Git/GitHub. Do not silently replace technologies or add Redis, a second database, microservices, real retailer integrations, or other infrastructure. Ask before expanding scope or changing PostgreSQL.

## Boundaries and safety invariants

React displays data and captures decisions; it never authorizes or decides eligibility. Shared Python services own deterministic policy, ownership, proposal, approval, request, and audit logic; REST and MCP entry points must call those same services. PostgreSQL is the durable authority. MCP must implement the required Streamable HTTP protocol/spec version and be exercised by an MCP client; REST alone is not MCP.

A help request is not approval. Proposals snapshot the exact order/item/action/conditions. Only an explicit user decision, checked server-side for owner, pending state, unchanged action, expiry, and eligibility, can create a simulated request. The LLM cannot approve itself and direct MCP calls cannot bypass checks. Declines never create requests. Prevent duplicates with transactional application logic and database uniqueness. Reconcile uncertain outcomes before retry; never claim success before persistence is confirmed. Use synthetic commerce data and disclose simulation.

## Conventions

Keep modules small and responsibilities explicit. Use type hints, Pydantic request/result schemas, clear domain errors, and stable snake_case Python names. Keep provider and MCP adapters separate from domain rules. Use UTC-aware timestamps and UUID identifiers. Keep frontend components accessible, responsive, and consistent with the original Amazon-inspired ReturnPilot design; do not use Amazon marks/assets or imply affiliation.

Use PostgreSQL constraints and foreign keys as safety backstops. SQLAlchemy sessions/transactions must have clear ownership and short lifetimes. Add schema changes only through Alembic migrations; do not silently create/alter tables at startup. Test PostgreSQL-specific constraints, locking, and transactions against real PostgreSQL, never assume SQLite proves correctness.

## Secrets and dependencies

Keep credentials in environment variables; never commit secrets or put provider keys in browser code, logs, fixtures, or screenshots. Keep `.env.example` credential-free. Add dependencies only when needed, explain material cost/licensing/runtime implications, and pin compatible versions using the repository's chosen package manager. Do not add paid services/cloud/hardware without discussing necessity and approval.

## Before modifying files

Inspect repository state and relevant files first. Follow the user's explicitly approved scope; preserve existing work. Make the smallest coherent change, do not start a later phase implicitly, and do not install packages or run destructive commands without authorization. Ask only when a material decision cannot be resolved from the approved specifications.

## Verification and reporting

Run appropriate tests when requested or required by the approved implementation step; distinguish tests run from plans. Report exact checks and actual outcomes, including failures and environment limits. Do not claim untested code works. Summarize changed files, architectural decisions, remaining issues, and risks. Never expose chain-of-thought; activity views show observable calls and state transitions only.
