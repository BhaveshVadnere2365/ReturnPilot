# ReturnPilot Implementation Plan

**Status:** All phases planned; no implementation phase is represented as complete.

The solo-developer critical path is: validate PostgreSQL and genuine MCP Streamable HTTP/version compatibility early; establish shared domain services and approval constraints without waiting on all MCP transport details; then connect the grant-protected MCP tool, orchestrator, and UI against agreed API contracts. Frontend work may proceed once its contracts and design are agreed. Reserve time for end-to-end proof and the demo. Keep all phases small and avoid infrastructure beyond the one PostgreSQL database.

## Phase 1 — Planning and specification

- **Objective:** Agree on consistent product, architecture, data, UX, testing, and working rules.
- **Dependencies:** Project brief and repository inspection.
- **Tasks:** Create/review `prd.md`, `architecture.md`, `design.md`, `data-model.md`, this plan, `testing-strategy.md`, `AGENTS.md`; confirm open decisions and current hackathon rules.
- **Deliverables:** Seven coherent planning files.
- **Acceptance:** Safety invariants agree across docs; unresolved provider/SDK details are recorded; no application implementation.
- **Verification:** Read-only cross-document ID/state/stack consistency review.
- **Risks:** Overplanning; resolve only decisions that affect safety or critical path.

## Phase 2 — Project foundation and PostgreSQL integration

- **Objective:** Establish React/Vite, FastAPI/Python, PostgreSQL, SQLAlchemy, Alembic, environment configuration, and run instructions.
- **Dependencies:** Phase 1 approval and selected supported tool versions.
- **Tasks:** Inspect repository again; create minimal app skeleton; configure shared settings and database session; migrations and synthetic seed; add credential-free environment example, including server-only grant-signing and FastAPI-to-MCP authentication settings; provide local run instructions.
- **Deliverables:** Running frontend/API, reachable PostgreSQL schema via migrations, repeatable synthetic fixture setup.
- **Acceptance:** Fresh database migrates; seed is repeatable; backend and frontend start; secrets stay server-side.
- **Verification:** Migration upgrade/downgrade where safe; health check; PostgreSQL integration smoke test.
- **Risks:** Local database setup/time, driver/config mismatch. Keep one PostgreSQL instance; SQLite is not a substitute.

## Phase 3 — Real MCP server and protocol verification

- **Objective:** Prove required MCP integration before building dependent workflows.
- **Dependencies:** Phase 2 shared configuration/database and early SDK/version selection. Protocol verification can proceed alongside independent domain-service work in Phase 4.
- **Tasks:** Build Python MCP entry point using supported SDK; serve Streamable HTTP; implement initialize, capabilities/tool discovery, tool schemas and structured errors; connect using an MCP client; establish authenticated FastAPI-to-MCP caller context; document launch configuration.
- **Deliverables:** Runnable MCP HTTP endpoint and protocol verification record.
- **Acceptance:** A real client initializes, lists tools, and invokes a harmless implemented tool over genuine Streamable HTTP; protocol/spec version and transport are verified against current requirements. This early transport proof does not block independent service implementation.
- **Verification:** MCP protocol/client tests and captured manual local smoke results; test actual Streamable HTTP transport, not REST lookalikes.
- **Risks:** SDK maturity/version mismatch. Validate this phase early and pin supported dependencies after verification.

## Phase 4 — Core backend services and approval workflow

- **Objective:** Implement deterministic rules and durable, safe state transitions shared by REST and MCP.
- **Dependencies:** PostgreSQL schema and shared service boundary from Phase 2. Domain services and PostgreSQL tests proceed independently of MCP transport completion; wire the MCP entry point when Phase 3 verification is available.
- **Tasks:** Order search/details, eligibility policy, proposal snapshots, ownership checks, approve/decline transactions, unique request creation, status/history, domain errors, and `proposal_created`, `approval_recorded`, `request_created`, `proposal_declined`, `proposal_expired`, and `request_status_checked` audit events. On authenticated explicit approval through FastAPI, issue a short-lived HMAC-SHA-256 grant binding trusted user, proposal ID, approved action, snapshot version/hash, and expiry. Securely authenticate the FastAPI-to-MCP caller; have the server-side MCP client invoke `create_return_request` with the grant, never exposing it to or relying on the LLM. Verify grant signature, caller identity, bindings, and expiry in the MCP server; pass verified trusted context to the shared service. Independently revalidate ownership, pending state, expiry, current eligibility, and persisted snapshot version/hash. Keep approval-record insertion, request creation, proposal completion, and required audit events in the same atomic PostgreSQL transaction. Use no grant/idempotency tables or new infrastructure.
- **Deliverables:** Service layer, REST endpoints, migration updates, backend tests.
- **Acceptance:** All lifecycle invariants pass on PostgreSQL; REST and MCP entry points use the same services; no request is created without a valid explicit approval grant and independent backend validation.
- **Verification:** pytest unit/API/PostgreSQL transaction/concurrency tests, including grant rejection and recovery cases listed in Phase 7.
- **Risks:** Race conditions and uncertain commit outcome. Use row locking, uniqueness, and reconciliation behavior.

## Phase 5 — AI orchestrator and MCP client integration

- **Objective:** Coordinate natural language and real MCP tools without delegating policy or approval authority to the model.
- **Dependencies:** MCP protocol/tool surface verified in Phase 3 and shared backend workflow available. Frontend development does not depend on this phase being complete.
- **Tasks:** Select LLM after cost/data-access review; implement server-side provider adapter and MCP client; prompt/tool loop; clarification and ambiguity handling; grounded response synthesis; timeouts and safe failure behavior.
- **Deliverables:** Working conversation endpoint with observable calls and structured result provenance.
- **Acceptance:** Model can search/check/describe but never receives the approval grant or initiates the consequential `create_return_request` call; failures do not produce false claims.
- **Verification:** Mocked provider tests plus one real provider integration/demo check, keeping keys out of browser.
- **Risks:** Provider cost, rate limits, tool-call variability. Keep deterministic service behavior and graceful fallback.

## Phase 6 — React frontend and Amazon-inspired UI

- **Objective:** Deliver the responsive commerce-support journey and explicit decision UI.
- **Dependencies:** Agreed API contracts and approved design specification. Does not depend on completion of the full LLM orchestrator; integrate the conversation when available.
- **Tasks:** Header/search/nav, conversation, order and ambiguity cards, eligibility and proposal, approve/decline states, activity timeline, status/history, accessibility/error states.
- **Deliverables:** Polished original ReturnPilot customer workspace.
- **Acceptance:** Visual hierarchy matches `design.md`; approval is explicit; states derive from backend responses; no Amazon assets or storefront features.
- **Verification:** Frontend component/accessibility checks and responsive viewport review.
- **Risks:** UI work expanding beyond workflow; prioritize the demo journey.

## Phase 7 — Integration, security and end-to-end testing

- **Objective:** Verify the complete persisted workflow and adversarial safety cases.
- **Dependencies:** Phases 2–6.
- **Tasks:** Exercise full tool/API/UI chain; ownership and invalid-state tests; concurrency/idempotency; restart persistence; error and uncertain-outcome recovery; setup review.
- **Deliverables:** Repeatable test suite and issue list resolved or documented.
- **Acceptance:** Mandatory cases in `testing-strategy.md` pass against PostgreSQL where relevant; all six required audit event types are verified; no false success; no duplicate requests; approval/request/completion/audit records are atomic.
- **Verification:** pytest, frontend checks, MCP protocol tests, browser end-to-end workflow, clean restart/status retrieval. Explicitly test missing, invalid, expired, modified, and replayed grants; caller/owner mismatch; concurrent approvals; and uncertain commit reconciliation by proposal ID and unique request reference. Replays may return an already committed result only after validating trusted actor/ownership, approved decision, proposal/request relationship, snapshot integrity, and completed state. For uncertain commits, show an unconfirmed status and retry creation only after reconciliation proves no request committed and the proposal remains valid and pending.
- **Risks:** Integration drift and limited solo time. Freeze noncritical features and protect demo rehearsal time.

## Phase 8 — Demo recording and hackathon submission

- **Objective:** Prepare a concise, verifiable submission.
- **Dependencies:** Working MVP and final requirements review.
- **Tasks:** Write run/setup and synthetic-data disclosure; verify repository visibility/license/reviewer access; record functioning demo under three minutes, public YouTube/Vimeo link; prepare description and actual product feedback for each tool; complete required Devpost fields; recheck current rules and date.
- **Deliverables:** Submission-ready repository and materials.
- **Acceptance:** Demo shows functioning MCP integration and complete workflow; all submission fields and reviewer access are checked; feedback reflects actual use, not guesses.
- **Verification:** Play back final video and run documented reviewer setup from a clean environment if feasible.
- **Risks:** Rules/fields can change, external service availability, deadline. Keep a time buffer and verify official Devpost sources shortly before submission.

## Early validation / critical path

First validate a local PostgreSQL connection/migration path, an MCP SDK that genuinely implements Streamable HTTP and the required spec version, and an MCP client initialize/list/invoke round trip. Then validate one LLM tool-calling loop and provider cost/data terms before committing. These checks reduce architectural risk; they do not authorize replacing PostgreSQL or the MCP requirement. All phases await explicit approval as described by the project workflow.
