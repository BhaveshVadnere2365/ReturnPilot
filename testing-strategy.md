# ReturnPilot Testing and Quality Plan

**Status:** Planned. PostgreSQL-specific correctness must be tested with PostgreSQL; SQLite is not considered evidence for PostgreSQL constraints, locking, or transaction behavior.

## Test layers

### Unit tests

- Deterministic policy rules for delivery age, item state, and synthetic policy cases.
- Order matching normalization and zero/one/multiple result semantics.
- Proposal snapshot creation and stable action hash.
- State transition validator and error mapping.
- Provider/orchestrator response grounding and clarification decisions using fakes.

### API integration tests

Run FastAPI against test PostgreSQL and exercise order lookup, proposal retrieval, approve/decline, request status/history, owner scoping, validation errors, and safe error responses. Verify the browser-facing API cannot set owner or approval state directly.

### MCP protocol and tool tests

Use an actual MCP client against the Streamable HTTP server. Verify initialize/version negotiation, capability response, tool discovery, JSON schemas, tool invocation, structured result/error mapping, connection failure, and request-creation approval checks. Test that MCP is not merely REST decorated with tool names.

### PostgreSQL persistence/integration tests

Apply Alembic migrations to a real isolated PostgreSQL test database. Verify foreign keys, checks, unique constraints, composite ownership/order-item relationship, transactions, row locks/concurrent approvals, rollback, atomic audit-event behavior, restart persistence, and idempotent seeding. Never infer these behaviors from SQLite.

### Frontend component and accessibility tests

Verify pending proposal copy/actions, disabled/loading state, declined and confirmed distinctions, actual request ID rendering, ambiguity selection, errors, keyboard operation, accessible labels/live announcements, and API-driven status. Include viewport/reflow review.

### End-to-end tests

Against a local integrated app and PostgreSQL, run a synthetic eligible order from natural-language prompt through MCP tools, proposal, explicit UI approval, persisted request confirmation, and subsequent status/history lookup. Include decline, ambiguity, ineligible, unknown, failure, and restart scenarios.

## Approval, authorization, concurrency and recovery matrix

| Scenario | Expected result | PRD links |
|---|---|---|
| Eligible order produces a pending proposal | Proposal persists; no request row exists | FR-005–006 |
| Creating proposal does not create request | Assert request count remains zero | FR-006, FR-010 |
| Declining proposal | Declined state/audit; request absent; future execution rejected | FR-009 |
| Valid approval | One approval and exactly one persisted request | FR-008, FR-010 |
| Repeated approval after commit | Return the existing request only after validating trusted actor, ownership, approved decision, proposal/request relationship, snapshot integrity, and completed proposal state; never create another request | FR-010, NFR-009 |
| Repeated decline | Return existing declined outcome only for the same valid decision by the authorized owner; reject conflict and create no request | FR-009 |
| Concurrent approval requests | PostgreSQL proposal row lock and unique approval/request constraints serialize attempts and yield at most one approval record and one request | FR-010, NFR-002 |
| Missing grant or invalid-signature grant | Reject MCP `create_return_request`; no approval/request/completion success events or request row | FR-014 |
| Expired grant | Reject creation; no request; do not treat grant expiry as a durable proposal state | FR-014 |
| Modified grant or grant binding mismatch (trusted user/owner, proposal, approved action, snapshot version, or snapshot hash) | Reject; no request or successful approval outcome | FR-008, FR-014 |
| Replayed grant/tool call | Never create a duplicate; return an already committed request only after trusted actor, ownership, approved decision, proposal/request relationship, snapshot integrity, and completed state are validated | FR-010, FR-014, NFR-009 |
| LLM or direct MCP caller attempts to bypass explicit approval | Reject without a valid server-issued grant bound to the authenticated actor and exact proposal/action/snapshot; no request persisted | FR-007–008, FR-014 |
| FastAPI-to-MCP trusted caller mismatch | Reject even if grant claims identify an owner; no request or approval record | FR-008, FR-014 |
| Invalid, expired, altered, foreign-owned proposal | Reject; no request persisted | FR-008–009 |
| Ineligible order | No executable proposal/request | FR-005 |
| Ambiguous order matches | Candidates returned; no guessed continuation/proposal | FR-003 |
| Unknown order or request | Safe not-found response; no data leak | FR-002, FR-011 |
| Failed operation | No false success; known transaction rollback is consistent | FR-016, NFR-007 |
| Unknown execution outcome | Return neutral unconfirmed status; reconcile by proposal ID and unique request reference before retry. Retry creation only after confirming no request committed and proposal remains valid and pending | NFR-009 |
| Transaction failure between approval and request | Atomic rollback or reconciled known outcome; approval record, request, proposal completion, and related audit events all commit or roll back together; no partial success | FR-008, FR-010, NFR-002 |
| Status lookup after application restart | Same persisted request ID/status/history is returned to owner | FR-011, FR-017 |
| Owner mismatch for order/proposal/request | No mutation or disclosure | FR-008, NFR-003 |
| LLM attempts to approve itself or call MCP request tool without grant | No approval path; only explicit authenticated user approval through FastAPI can cause the server-side MCP client to invoke the consequential tool | FR-007–008, FR-014 |

## Failure injection and observability

Inject MCP timeout, LLM/provider error, database disconnect before and after commit boundary, malformed tool result, missing/invalid/expired/modified/replayed grant, FastAPI-to-MCP caller or owner mismatch, and frontend network loss. Verify customer-visible messaging, correlation IDs, preserved persisted state, and no chain-of-thought/secrets/grants in logs. A lost response or unknown commit outcome must produce a neutral unconfirmed response and be reconciled by proposal ID and unique request reference before retry; retry request creation only after confirming no request committed and the proposal remains valid and pending.

## Acceptance traceability

PRD FR-001–004: conversation and order search/clarification API and E2E tests. FR-005–006: policy and proposal unit/PostgreSQL tests. FR-007–010: UI decision plus service/API/MCP authorization, concurrency and state tests. FR-011–012, FR-017: persistence, audit, restart status tests. FR-013–014: MCP protocol/tool client tests. FR-015–016: frontend component/accessibility and failure tests. NFR-001–010: migration, PostgreSQL integration, security, secret scan/config review, and reliability cases above.

## Exit criteria

All safety matrix cases pass, with PostgreSQL for database-specific assertions; MCP real-client round trip is demonstrated; end-to-end happy path and key failures pass; no test describes an unverified behavior as proven. Record actual command, environment, and results during implementation; this plan itself is not evidence that tests have run.
