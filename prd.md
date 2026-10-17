# ReturnPilot Product Requirements Document

**Status:** Planned specification  
**Product:** ReturnPilot, Amazon Developer Hackathon 2026 (Alexa+ track)

## Overview and problem

ReturnPilot helps a customer resolve a synthetic commerce order issue through a grounded, auditable workflow. Customers often need to identify an order, understand its return eligibility, and decide what to do next. A conversational assistant can reduce that effort, but must never turn a request for help into an unapproved consequential action.

The MVP uses synthetic commerce data and simulates replacement requests. It does not connect to real shopping accounts, issue refunds, create shipping labels, or ship goods. It is an original ReturnPilot experience, not an official Amazon application.

## Users and needs

- **Demo customer:** Wants to describe a problem naturally, find the correct order, see applicable rules, choose whether to proceed, and retrieve a confirmed request later.
- **Hackathon judge/developer:** Needs to see a functioning Alexa+ technology path, understandable setup, and a reliable demonstration of the end-to-end workflow.

## Goals and success measures

1. Complete the happy path from message to persisted simulated request and status lookup in one demo session.
2. Show a real MCP server over Streamable HTTP, initialized and used through an MCP client, using a compatible spec version (minimum stated in current rules: 2025-11-25).
3. Ensure every submitted request references a valid, explicitly approved proposal; proposal creation alone creates no request.
4. Prevent duplicate requests on repeated approval and concurrent execution.
5. Persist workflow and audit records in PostgreSQL across restarts.
6. Demonstrate ambiguous, unknown, ineligible, declined, and failed-operation behavior without fabricated success.

## User journey

1. Customer describes an order issue and desired resolution.
2. Assistant searches synthetic orders. For multiple matches, it presents candidates and asks the customer to choose; for no match it explains how to retry.
3. Assistant retrieves the chosen order and item details.
4. Backend policy service determines eligibility and reasons. Ineligible results end the proposal path.
5. Backend creates a pending proposal that snapshots the exact order, item, replacement action, and conditions.
6. UI displays the proposal and asks for an explicit approve/decline decision.
7. On decline, the proposal is marked declined and no request exists. On approval, backend validates owner, state, and action, then transactionally records approval and creates at most one request.
8. UI reports success only after persisted request data is returned. Customer can retrieve request status later.

## Functional requirements

| ID | Requirement |
|---|---|
| FR-001 | Accept natural-language issue descriptions and resolution intent through the workspace. |
| FR-002 | Find synthetic orders by order ID or product details, scoped to the demo user/session. |
| FR-003 | Return multiple candidates without guessing; require user clarification before continuing. |
| FR-004 | Retrieve order, item, order date, delivery state, and relevant product details. |
| FR-005 | Evaluate eligibility with deterministic backend rules and return structured reasons. |
| FR-006 | Persist a pending proposal containing an immutable snapshot of the exact order, item, resolution, and conditions. |
| FR-007 | Present the exact pending action and require explicit customer approval or decline. |
| FR-008 | Validate proposal ownership, pending state, unchanged action, and eligibility on the backend before execution. |
| FR-009 | Decline a pending proposal without creating a request; reject invalid state transitions. |
| FR-010 | Create and persist at most one simulated request for an approved proposal. |
| FR-011 | Retrieve persisted request status/history without creating another request. |
| FR-012 | Record `proposal_created`, `approval_recorded`, `request_created`, `proposal_declined`, `proposal_expired`, and `request_status_checked` events without logging secrets. |
| FR-013 | Expose `find_order`, `get_order_details`, `check_return_eligibility`, `create_return_request`, and `get_return_status` through a real MCP Streamable HTTP server. `create_return_request` must use the same trusted, explicitly user-approved flow, validate the proposal and snapshot, and preserve the atomic approval/request transaction. |
| FR-014 | An LLM tool call or tool-supplied argument alone never authorizes request creation. MCP request creation must use trusted approval intent and backend validation of actor/ownership, proposal state, eligibility, expiry, and snapshot integrity; it cannot bypass the atomic approval/request workflow. |
| FR-015 | Show actual observable tool calls/results and workflow events in the UI; do not expose model chain-of-thought. |
| FR-016 | Display clear loading, empty, ambiguous, ineligible, error, pending, declined, and confirmed states. |
| FR-017 | Preserve required workflow data across application restarts using PostgreSQL. |

## Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-001 | PostgreSQL is the only primary database; SQLAlchemy provides persistence and Alembic manages schema migrations. |
| NFR-002 | Use database transactions, foreign keys, uniqueness constraints, and indexes to preserve workflow integrity. |
| NFR-003 | Enforce authorization and business rules on the server; the frontend is not trusted. |
| NFR-004 | Keep all credentials in environment variables; never expose provider keys to frontend bundles. |
| NFR-005 | Responsive, keyboard-operable UI with labeled controls, sufficient contrast, and understandable errors. |
| NFR-006 | Keep implementation and infrastructure small enough for a solo developer and the hackathon deadline. |
| NFR-007 | Avoid unsupported claims; assistant statements about orders, policy, and outcomes must be grounded in persisted/backend results. |
| NFR-008 | Logs and audit records must avoid secrets and minimize personal data; demo data is synthetic. |
| NFR-009 | Handle repeated/concurrent submissions idempotently and represent uncertain execution honestly. |
| NFR-010 | Setup documentation must allow a reviewer to run the project; verify final requirements and access instructions against current Devpost rules. |

## User stories and acceptance criteria

- **US-01 Find an order (FR-002–004):** As a customer, I can locate the order relevant to my issue. Given one match, the selected order is shown with actual details. Given zero matches, the UI offers retry guidance. Given multiple matches, the assistant requests a selection and performs no eligibility check on a guessed order.
- **US-02 Check eligibility (FR-005):** As a customer, I can see a deterministic decision and its policy reasons. Ineligible items cannot produce an executable proposal.
- **US-03 Review a proposal (FR-006–007):** As a customer, I can inspect the exact item, replacement, and conditions. Creating or displaying it does not create a request.
- **US-04 Approve (FR-008, FR-010):** As a customer, I can explicitly approve the displayed action. Backend validation succeeds once, and the UI displays the persisted request ID/status. Repeating approval returns the existing outcome or a safe conflict without a second request.
- **US-05 Decline (FR-009):** As a customer, I can decline. The proposal becomes declined and no request can be created from it.
- **US-06 Check status (FR-011):** As a customer, I can revisit an existing request and see its persisted current status/history, including after an application restart.
- **US-07 Recover from failure (FR-016):** As a customer, I receive a clear failure message and safe next step. An uncertain operation is not described as successful or blindly retried.
- **US-08 Inspect activity (FR-012, FR-015):** As a customer/judge, I can see observable workflow/tool events without hidden reasoning or credentials.

## MVP scope and exclusions

Included: synthetic orders and items; one clearly identified demo user/session; natural-language orchestration; five MCP tools; deterministic policy checks; pending proposal and approval/decline; simulated request; persisted status/history and audit; responsive customer workspace; tests of rules and safety.

Excluded: real retailer/private APIs, real money/refunds/shipping, voice/device integration, complex authentication, multiple agents, microservices, Redis, shopping cart/checkout, analytics dashboard, and unapproved features. Production would require stronger identity, authorization, external-operation reconciliation, and operational monitoring.

## Error and edge cases

- Unknown order: no proposal; explain search options.
- Multiple matches: list minimal distinguishing details and wait for selection.
- Missing item/resolution: ask a focused clarification.
- Ineligible item: show backend reasons; do not create executable proposal.
- Expired, declined, altered, foreign-owned, or otherwise invalid proposal: reject safely.
- Database/API/MCP/LLM failure: preserve known state, surface recoverable error, avoid claiming success.
- Approval timeout/connection loss after dispatch: report the outcome as unconfirmed until reconciled; do not assume a separate uncertainty state was persisted or issue a second create blindly.
- Repeated/concurrent approval: one request maximum; return known persisted result when safe.
- Status request for unknown/foreign request: do not disclose whether another session owns it.

## Approval and safety invariants

Help-seeking is not consent. Proposal creation and eligibility checks are non-consequential. The proposal is a server-created snapshot of exact action and conditions. Only an explicit user decision validated by the backend can authorize the existing atomic approval/request workflow. An LLM tool call or tool-supplied argument alone never authorizes request creation. The MCP `create_return_request` tool must use that same trusted, explicitly user-approved flow and validate the proposal, ownership, state, expiry, current eligibility, and snapshot integrity; it cannot approve its own call or bypass the approval/request transaction. Declined/non-pending proposals never create requests. Ownership is checked for every lookup/action. Database constraints and transactions provide duplicate protection. Unknown outcomes remain unconfirmed until reconciliation; no separately persisted uncertainty state is assumed. UI success is based on a persisted backend response.

## Hackathon requirements and confirmation items

Current official rules list the Alexa+ option as a working Agent Skill or self-hosted MCP server implementing MCP 2025-11-25 or later over Streamable HTTP, with a separate simulated Alexa+ web experience alternative. This project plans the actual self-hosted MCP path. Code must demonstrate runtime technology use and the demo must show it functioning. Submission includes a project description, GitHub repository URL, a public YouTube/Vimeo demo under three minutes, and product feedback for each tool/API/SDK. Repository must be public with a visible open-source license or private and shared with the named reviewers; setup/run instructions and judge access are required. Confirm all details on the official [rules](https://amazonappdev2026.devpost.com/rules), [resources](https://amazonappdev2026.devpost.com/resources), and [FAQ](https://amazonappdev2026.devpost.com/details/faqs) before submission; rules may change. Deadline stated there: Oct 23, 2026 12:00 PM PDT (Oct 24, 2026 12:30 AM IST).

## Definition of Done

All FRs in MVP scope are implemented and acceptance-tested; core data persists in PostgreSQL; MCP initialization, discovery, and tool invocation are demonstrated over Streamable HTTP; approval and duplicate protections pass PostgreSQL-backed tests; failure and ambiguity states are honest; UI is responsive and accessible; setup and synthetic-data disclosure are documented; demo shows the working flow within the limit; submission requirements are rechecked. No item is considered done solely because it is described in documentation.
