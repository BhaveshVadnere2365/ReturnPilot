# ReturnPilot UI/UX Design Specification

**Status:** Planned, no UI implementation in this phase.

## Design direction

Create a polished, familiar commerce-support workspace with an original ReturnPilot identity. Use Amazon-inspired layout conventions—dark utility header, prominent search, compact order information, warm orange primary action, and clear blue links—without Amazon logos, proprietary assets, copied brand wording, or any suggestion that ReturnPilot is official. This is a support workflow, not a storefront: no cart, checkout, or payment UI.

## Design tokens

| Token | Value / convention |
|---|---|
| Header navy | `#131A22` |
| Secondary navy | `#232F3E` |
| Primary orange | `#F3A847` (hover `#E99A2E`, dark text) |
| Link blue | `#176A8A` |
| Page background | `#F3F4F5` |
| Surface | `#FFFFFF` |
| Soft section | `#F7F8F8` |
| Main text | `#17212B` |
| Muted text | `#56616C` |
| Border | `#D5D9DD` |
| Success | `#16794B` on pale green surface |
| Pending | `#8B5B00` on pale amber surface |
| Error | `#B42318` on pale red surface |
| Typography | System sans-serif stack; 14–16px body, 12–13px meta, 22–28px page title |
| Spacing | 4px base; common steps 8, 12, 16, 24, 32px |
| Borders | 1px neutral; dividers distinct from focus rings |
| Radii | 4px controls, 8px cards, pill only for compact status badges |
| Shadows | Subtle elevation on overlays only; cards primarily use borders |
| Focus | Visible 2px high-contrast outline with offset; never color-only state |

## Page structure and hierarchy

### 1. Top header

Desktop header uses a dark navy horizontal band. Left: ReturnPilot wordmark/text in original styling. Center: wide search input with an accessible label such as “Search orders or describe an issue” and orange submit control. Right: clearly labeled “Demo account” area and Request History link. On mobile, brand and account/history controls occupy the first row; search becomes full-width below. No Amazon mark or assets.

### 2. Secondary navigation

A shorter charcoal/navy row provides Orders, Returns & Replacements, Help, and Request History links. Use a clear active underline or border and semantic navigation. Mobile can wrap or use an accessible compact menu; key workflow actions remain reachable without hover.

### 3. Main support workspace

Near-white page background with a centered content column. Heading (“How can we help with an order?”) and brief synthetic-demo disclosure sit above a small set of suggested issue prompts. The conversation area is a restrained sequence of customer and assistant messages with a labeled message composer. Keep it visually commerce-oriented and compact, not a generic analytics dashboard. Assistant responses contain links/cards to actual order and proposal records.

Desktop main column can sit beside a narrower order context panel; tablet stacks or narrows panels; mobile uses a single column. Do not hide approval controls below an inaccessible scroll trap.

### 4. Order summary

White bordered card with neutral product-image placeholder (original generic illustration or CSS placeholder), product name, order ID, order date, delivery state, and item selection if needed. Eligibility is shown only after backend evaluation, with a plain-language reason and restrained status label. Unknown orders render helpful empty state. Ambiguous matches appear as compact selectable order cards showing enough distinguishing details to choose safely.

### 5. Replacement proposal card

Distinct white card with an amber “Awaiting your approval” badge, order/item reference, exact replacement action, and applicable conditions. State explicitly that nothing has been submitted yet. Place prominent orange “Approve replacement” and secondary neutral “Decline” actions together, with accessible labels. Before action, controls are enabled only for the pending proposal. During submission, disable both and expose a live progress message. After decline, show “Declined; no request was submitted.” After approval, replace the pending card with the persisted request confirmation. Never present pending and submitted states as equivalent.

### 6. Activity timeline

Compact vertical list near the conversation/context area: order found, details retrieved, policy checked, proposal created, approval received, request persisted. Each event has time and human-readable outcome; tool events are observable and grounded in returned data. Show failures clearly. Do not expose private chain-of-thought, hidden prompts, secrets, or raw stack traces.

### 7. Confirmation and history

Success view appears only after backend confirms commit and returns persisted request ID/status. Show request ID, current status, linked order/item, timestamp, and “View request”/history link. History list can open a request detail showing status history from persisted records. Refresh/restart must not depend on browser-only state.

## Feedback and interaction states

| State | Presentation and behavior |
|---|---|
| Loading/searching | Stable card skeleton or progress text; announce status accessibly; prevent duplicate submission. |
| No results | Explain that no matching demo order was found; offer search/ID retry. |
| Ambiguous | Present candidate choices and ask user to select; do not guess or create proposal. |
| Ineligible | Show backend reason and available next step; no approval CTA. |
| Proposal pending | Amber status, exact action and conditions, clear not-submitted explanation, explicit approve/decline. |
| Processing decision | Disable decision controls; show progress and retain proposal identity. |
| Declined | Confirm declined state and that no request was created. |
| Error | Plain language with safe retry guidance; distinguish known failure from unknown outcome. |
| Outcome uncertain | Say the result is being checked; do not offer a second consequential submit until reconciled. |
| Success | Green restrained confirmation with actual persisted request ID and status. |
| Empty history | Explain that no simulated requests exist yet and link to start a support flow. |

## Accessibility and responsive behavior

Use semantic header/nav/main/section headings, properly associated labels, keyboard-accessible order choices and buttons, logical focus order, visible focus, sufficient text/control contrast, and live regions for asynchronous results. Do not rely only on color or icons. Respect zoom and narrow viewport reflow; target usable controls on touch. Errors must remain visible and tied to the relevant control. Focus moves to meaningful result headings after major transitions without unexpectedly stealing focus during typing.

## Content and brand guardrails

Use ReturnPilot branding and synthetic order examples. Disclose that commerce is simulated. Use original neutral product placeholders and wording. Avoid Amazon logos, proprietary images, copied copy, or claims of affiliation. Keep the visual analogy at the level of familiar commerce layout patterns.
