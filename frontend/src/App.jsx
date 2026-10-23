import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorMessage, isAuthenticationError } from './api.js'

function dateLabel(value) {
  if (!value) return 'Date unavailable'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Date unavailable' : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(date)
}

function statusLabel(value = '') {
  return value.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase())
}

function orderFromEvents(events = []) {
  for (const event of [...events].reverse()) {
    const result = event.result || {}
    const order = result.order || (Array.isArray(result.matches) && result.matches.length === 1 ? result.matches[0] : null)
    if (order) return order
  }
  return null
}

function candidatesFromEvents(events = []) {
  const latestAmbiguousResult = [...events].reverse().find((event) => Array.isArray(event.result?.matches) && event.result.matches.length > 1)
  return latestAmbiguousResult?.result.matches || []
}

export default function App() {
  const [session, setSession] = useState({ loading: true, displayName: 'Demo account', error: '' })
  const [view, setView] = useState('workspace')
  const [query, setQuery] = useState('')
  const [orderSearchQuery, setOrderSearchQuery] = useState('')
  const [orderSearchLoading, setOrderSearchLoading] = useState(false)
  const [orderDetailsLoading, setOrderDetailsLoading] = useState(false)
  const [orderSearchError, setOrderSearchError] = useState('')
  const [orderSearchMatches, setOrderSearchMatches] = useState([])
  const [orderSearchNoResults, setOrderSearchNoResults] = useState(false)
  const [messages, setMessages] = useState([
    { role: 'assistant', text: 'Tell me which order needs help and what happened. I can look up synthetic demo orders and check the available options.' },
  ])
  const [toolEvents, setToolEvents] = useState([])
  const [latestCandidates, setLatestCandidates] = useState([])
  const [order, setOrder] = useState(null)
  const [eligibility, setEligibility] = useState(null)
  const [proposal, setProposal] = useState(null)
  const [request, setRequest] = useState(null)
  const [conversationError, setConversationError] = useState('')
  const [pending, setPending] = useState(false)
  const [decisionPending, setDecisionPending] = useState(false)
  const [requestIdInput, setRequestIdInput] = useState('')
  const [history, setHistory] = useState(null)
  const [historyError, setHistoryError] = useState('')
  const [historyLoading, setHistoryLoading] = useState(false)
  const composerRef = useRef(null)
  const returnsRef = useRef(null)

  const startSession = useCallback(async () => {
    setSession({ loading: true, displayName: 'Demo account', error: '' })
    try {
      const result = await api.startDemoSession()
      setSession({ loading: false, displayName: result.display_name || 'Demo account', error: '' })
      setView('workspace')
    } catch (error) {
      setSession({ loading: false, displayName: 'Demo account', error: errorMessage(error) })
    }
  }, [])

  function handleApiError(error) {
    if (isAuthenticationError(error)) {
      setSession((current) => ({ ...current, error: errorMessage(error) }))
      return null
    }
    return errorMessage(error)
  }

  useEffect(() => { startSession() }, [startSession])

  async function selectOrder(orderId) {
    setOrderDetailsLoading(true)
    setOrderSearchError('')
    try {
      const selectedOrder = await api.getOrderDetails(orderId)
      if (order && order.order_id !== selectedOrder.order_id) {
        setProposal(null)
        setRequest(null)
      }
      setOrder(selectedOrder)
      setEligibility(null)
      setOrderSearchMatches([])
      setLatestCandidates([])
      setView('workspace')
    } catch (error) {
      const message = handleApiError(error)
      if (message) setOrderSearchError(message)
    } finally {
      setOrderDetailsLoading(false)
    }
  }

  async function searchOrders(event) {
    event.preventDefault()
    const searchTerm = orderSearchQuery.trim()
    if (!searchTerm || orderSearchLoading || session.loading || session.error) return
    setOrderSearchLoading(true)
    setOrderSearchError('')
    setOrderSearchMatches([])
    setOrderSearchNoResults(false)
    try {
      const result = await api.searchOrders(searchTerm)
      const matches = Array.isArray(result.matches) ? result.matches : []
      if (matches.length === 1) {
        await selectOrder(matches[0].order_id)
      } else {
        setOrderSearchMatches(matches)
        setOrderSearchNoResults(matches.length === 0)
      }
    } catch (error) {
      const message = handleApiError(error)
      if (message) setOrderSearchError(message)
    } finally {
      setOrderSearchLoading(false)
    }
  }

  const askAssistant = useCallback(async (text) => {
    const clean = text.trim()
    if (!clean || pending || session.loading) return
    setMessages((current) => [...current, { role: 'customer', text: clean }])
    setQuery('')
    setPending(true)
    setConversationError('')
    setLatestCandidates([])
    try {
      const result = await api.converse(clean)
      setMessages((current) => [...current, { role: 'assistant', text: result.reply, state: result.status }])
      setToolEvents((current) => [...current, ...(result.tool_events || [])])
      setLatestCandidates(candidatesFromEvents(result.tool_events))
      const nextOrder = orderFromEvents(result.tool_events)
      if (nextOrder) {
        if (order && order.order_id !== nextOrder.order_id) {
          setProposal(null)
          setRequest(null)
          setEligibility(null)
        }
        setOrder(nextOrder)
      }
      if (result.proposal) setProposal(result.proposal)
    } catch (error) {
      const message = handleApiError(error)
      if (message) {
        setConversationError(message)
        setMessages((current) => [...current, { role: 'assistant', text: message, error: true }])
      }
    } finally {
      setPending(false)
    }
  }, [order, pending, session.loading])

  async function checkItem(orderId, itemId) {
    setEligibility({ loading: true, orderItemId: itemId })
    try {
      const result = await api.checkEligibility(orderId, itemId)
      setEligibility({ ...result, orderItemId: itemId })
      setToolEvents((current) => [...current, {
        tool: 'check_return_eligibility',
        arguments: { order_id: orderId, order_item_id: itemId },
        result: { eligibility: result },
      }])
    } catch (error) {
      const message = handleApiError(error)
      if (message) setEligibility({ error: message, orderItemId: itemId })
      else setEligibility(null)
    }
  }

  async function refreshProposal(proposalId) {
    const current = await api.getProposal(proposalId)
    setProposal(current)
    if (current.request) setRequest(current.request)
    return current
  }

  async function reconcileProposal() {
    if (!proposal?.proposal_id) return
    try {
      const current = await refreshProposal(proposal.proposal_id)
      if (current.state === 'pending' && !current.request) {
        setConversationError('No request was found for this proposal. It remains pending; review it before deciding again.')
      } else if (current.request) {
        setRequest(current.request)
        setProposal(current)
      }
    } catch {
      setConversationError('The outcome is still unconfirmed. Check the proposal status again before retrying.')
    }
  }

  async function decide(decision) {
    if (!proposal || proposal.state !== 'pending' || decisionPending) return
    setDecisionPending(true)
    setConversationError('')
    try {
      if (decision === 'decline') {
        const result = await api.declineProposal(proposal)
        setProposal((current) => ({ ...current, ...result }))
      } else {
        const result = await api.approveProposal(proposal)
        if (result.status === 'unconfirmed') {
          setProposal((current) => ({ ...current, state: 'checking' }))
          try {
            const reconciled = await refreshProposal(proposal.proposal_id)
            if (reconciled.state === 'pending' && !reconciled.request) {
              setConversationError('The approval was not confirmed. The proposal is still pending; review it before trying again.')
            }
          } catch {
            setConversationError('Checking request status. Do not approve again until the outcome is confirmed.')
          }
        } else if (result.request_id && result.outcome === 'confirmed') {
          setRequest(result)
          setProposal((current) => ({ ...current, state: 'completed', request: result }))
        }
      }
    } catch (error) {
      const message = handleApiError(error)
      if (message) setConversationError(message)
      if (error.status === 409) {
        try { await refreshProposal(proposal.proposal_id) } catch { /* keep the safe conflict visible */ }
      }
    } finally {
      setDecisionPending(false)
    }
  }

  async function lookupHistory(event) {
    event.preventDefault()
    const id = requestIdInput.trim()
    if (!id || historyLoading) return
    setHistoryLoading(true)
    setHistoryError('')
    setHistory(null)
    try {
      const result = await api.getRequestHistory(id)
      setHistory(result)
    } catch (error) {
      const message = handleApiError(error)
      if (message) setHistoryError(message)
    } finally {
      setHistoryLoading(false)
    }
  }

  function showRequest(requestView) {
    setRequest(requestView)
    setRequestIdInput(requestView.request_id)
    setView('history')
    setHistory(null)
  }

  function openReturns() {
    setView('returns')
    returnsRef.current?.focus()
    returnsRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }

  function openHelp() {
    setView('help')
    composerRef.current?.focus()
  }

  function openOrders() {
    setView('workspace')
    document.getElementById('order-context')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }

  const displayedOrder = order || orderFromEvents(toolEvents)

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-main">
          <a className="brand" href="#workspace" onClick={() => setView('workspace')} aria-label="ReturnPilot home">
            <span className="brand-mark" aria-hidden="true">R</span>
            <span>Return<span className="brand-accent">Pilot</span></span>
          </a>
          <form className="header-search" onSubmit={searchOrders}>
            <label className="sr-only" htmlFor="header-search">Search orders by reference, product, or SKU</label>
            <input id="header-search" value={orderSearchQuery} onChange={(event) => setOrderSearchQuery(event.target.value)} placeholder="Search orders by reference, product, or SKU" />
            <button type="submit" disabled={orderSearchLoading || orderDetailsLoading || !orderSearchQuery.trim() || session.loading || Boolean(session.error)} aria-label="Search orders">Search</button>
          </form>
          <div className="account-tools">
            <div className="account-label"><span className="account-kicker">Demo account</span><strong>{session.displayName}</strong></div>
            <button className="header-link" onClick={() => setView('history')}>Request history</button>
          </div>
        </div>
        {(orderSearchLoading || orderDetailsLoading || orderSearchError || orderSearchNoResults || orderSearchMatches.length > 1) && <div className="order-search-results" aria-live="polite">
          {orderSearchLoading && <p role="status">Searching demo orders…</p>}
          {orderDetailsLoading && <p role="status">Loading selected order details…</p>}
          {orderSearchError && <p className="order-search-error" role="alert">{orderSearchError}</p>}
          {orderSearchNoResults && <p role="status">No matching demo orders were found. Check the reference, product name, or SKU.</p>}
          {orderSearchMatches.length > 1 && <section aria-label="Order search results"><p className="order-search-title">Select an order ({orderSearchMatches.length} matches)</p><ul>{orderSearchMatches.map((match) => <li key={match.order_id}><button type="button" className="order-search-match" onClick={() => selectOrder(match.order_id)} disabled={orderDetailsLoading}><strong>{match.external_order_ref}</strong><span>{match.items?.map((item) => item.product_name).join(', ') || 'Order details available'}</span><span>{dateLabel(match.ordered_at)} · {statusLabel(match.delivery_status)}</span></button></li>)}</ul></section>}
        </div>}
      </header>
      <nav className="subnav" aria-label="Main navigation">
        <button className={view === 'workspace' ? 'nav-item active' : 'nav-item'} aria-current={view === 'workspace' ? 'page' : undefined} onClick={openOrders}>Orders</button>
        <button className={view === 'returns' ? 'nav-item active' : 'nav-item'} aria-current={view === 'returns' ? 'page' : undefined} onClick={openReturns}>Returns &amp; replacements</button>
        <button className={view === 'help' ? 'nav-item active' : 'nav-item'} aria-current={view === 'help' ? 'page' : undefined} onClick={openHelp}>Help</button>
        <button className={view === 'history' ? 'nav-item active' : 'nav-item'} aria-current={view === 'history' ? 'page' : undefined} onClick={() => setView('history')}>Request history</button>
      </nav>

      {session.error && <div className="session-banner" role="alert"><span>{session.error}</span><button onClick={startSession}>Start demo session</button></div>}
      {session.loading && <div className="session-loading" role="status">Connecting to the synthetic demo account…</div>}

      {view !== 'history' ? (
        <main id="workspace" className="page-layout">
          <section className="workspace-column" aria-labelledby="page-title">
            <div className="page-intro">
              <p className="eyebrow">Synthetic commerce support</p>
              <h1 id="page-title">How can we help with an order?</h1>
              <p>Describe what happened. ReturnPilot uses synthetic demo records and does not connect to real shopping accounts.</p>
            </div>
            <div className="suggestions" aria-label="Suggested questions">
              {['Find order RP-10001', 'Check a damaged item', 'I need help with a replacement'].map((text) => (
                <button key={text} className="suggestion" disabled={pending || session.loading} onClick={() => askAssistant(text)}>{text}<span aria-hidden="true">↗</span></button>
              ))}
            </div>

            <section className="conversation-card" id="help-center" aria-labelledby="conversation-title">
              <div className="card-heading"><div><p className="eyebrow">Order support</p><h2 id="conversation-title">Conversation</h2></div><span className="secure-label"><span aria-hidden="true">●</span> Demo session</span></div>
              <div className="message-list" aria-live="polite" aria-relevant="additions text">
                {messages.map((message, index) => (
                  <article key={`${message.role}-${index}`} className={`message ${message.role} ${message.error ? 'message-error' : ''}`}>
                    <span className="message-avatar" aria-hidden="true">{message.role === 'customer' ? 'You' : 'R'}</span>
                    <div><span className="message-author">{message.role === 'customer' ? 'You' : 'ReturnPilot'}</span><p>{message.text}</p>{message.state === 'needs_clarification' && <span className="inline-hint">Please choose or clarify before continuing.</span>}</div>
                  </article>
                ))}
                {pending && <div className="loading-line" role="status"><span className="spinner" aria-hidden="true" />Checking your message…</div>}
              </div>
              {conversationError && <div className="inline-error" role="alert">{conversationError}</div>}
              <form className="composer" onSubmit={(event) => { event.preventDefault(); askAssistant(query) }}>
                <label htmlFor="message-input">Describe the order issue or ask a question</label>
                <textarea ref={composerRef} id="message-input" rows="3" maxLength="2000" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="For example, I received a damaged item in order RP-10001…" disabled={pending || session.loading || Boolean(session.error)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); askAssistant(query) } }} />
                <div className="composer-footer"><span>Enter to send · Shift + Enter for a new line</span><button className="button button-primary" type="submit" disabled={pending || !query.trim() || session.loading}>Send message</button></div>
              </form>
            </section>

            {latestCandidates.length > 1 && <section className="panel candidates" aria-labelledby="candidate-title"><div className="card-heading"><div><p className="eyebrow">Clarification needed</p><h2 id="candidate-title">Which order do you mean?</h2></div></div><div className="candidate-list">{latestCandidates.map((candidate) => <button key={candidate.order_id} className="candidate-card" onClick={() => askAssistant(`The order is ${candidate.external_order_ref}.`)}><strong>Order {candidate.external_order_ref}</strong><span>{candidate.items?.map((item) => item.product_name).join(', ') || 'Order details available'}</span><span>{dateLabel(candidate.ordered_at)} · {statusLabel(candidate.delivery_status)}</span></button>)}</div></section>}

            <section className="returns-workflow" id="returns-workflow" ref={returnsRef} tabIndex={-1} aria-labelledby="returns-title">
              <div className="page-intro"><p className="eyebrow">Simulated return support</p><h2 id="returns-title">Returns &amp; replacements</h2></div>
              {proposal && <ProposalCard proposal={proposal} decisionPending={decisionPending} onDecision={decide} onViewRequest={showRequest} onReconcile={reconcileProposal} />}
              {request && <RequestConfirmation request={request} onView={() => showRequest(request)} />}
              {!proposal && !request && <div className="panel returns-empty"><p>Start with an order to check an item and review any available replacement proposal.</p><button className="text-button" onClick={openHelp}>Find an order or get help</button></div>}
            </section>

            <ActivityTimeline events={toolEvents} />
          </section>

          <aside className="context-column" id="order-context" aria-label="Order context">
            <section className="panel context-panel">
              <div className="card-heading"><div><p className="eyebrow">Your order</p><h2>Order details</h2></div><span className="context-icon" aria-hidden="true">▤</span></div>
              {displayedOrder ? <OrderDetails order={displayedOrder} eligibility={eligibility} onCheck={checkItem} /> : <div className="empty-context"><div className="empty-illustration" aria-hidden="true">□</div><h3>No order selected</h3><p>Search by order reference, product name, or SKU to see synthetic order details here.</p></div>}
              {orderDetailsLoading && <p className="loading-line" role="status">Loading selected order details…</p>}
            </section>
            <section className="simulation-note"><span className="note-icon" aria-hidden="true">i</span><div><strong>Simulation only</strong><p>Requests are saved in the demo system. No physical goods are returned or shipped.</p></div></section>
            {eligibility && !eligibility.loading && <section className={`eligibility-card ${eligibility.error ? 'is-error' : eligibility.eligible ? 'is-eligible' : 'is-ineligible'}`} aria-live="polite"><p className="eyebrow">Eligibility check</p>{eligibility.error ? <p>{eligibility.error}</p> : <><strong>{eligibility.eligible ? 'Eligible for a simulated replacement' : 'Not eligible'}</strong>{eligibility.reasons?.length > 0 && <ul>{eligibility.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}<span className="meta">Policy {eligibility.policy_version}</span></>}</section>}
          </aside>
        </main>
      ) : (
        <main className="history-page" id="request-history">
          <div className="page-intro"><p className="eyebrow">Persisted demo records</p><h1>Request history</h1><p>Look up a request using its ID to see its current status and recorded activity.</p></div>
          <section className="panel history-lookup"><form onSubmit={lookupHistory}><label htmlFor="request-id">Request ID</label><div className="lookup-row"><input id="request-id" value={requestIdInput} onChange={(event) => setRequestIdInput(event.target.value)} placeholder="Paste a request ID" /><button className="button button-primary" type="submit" disabled={!requestIdInput.trim() || historyLoading}>{historyLoading ? 'Looking up…' : 'View request'}</button></div></form>{historyError && <p className="inline-error" role="alert">{historyError}</p>}</section>
          {historyLoading && <p className="loading-line" role="status"><span className="spinner" aria-hidden="true" />Loading persisted request history…</p>}
          {history && <RequestHistoryPanel history={history} />}
          {!history && !historyError && !historyLoading && <div className="empty-history"><span aria-hidden="true">◷</span><h2>No request selected</h2><p>Confirmed requests can be opened here from their confirmation card.</p></div>}
        </main>
      )}
      <footer className="site-footer"><span>ReturnPilot</span><span>Independent synthetic demo · Not affiliated with any retailer</span></footer>
    </div>
  )
}

function OrderDetails({ order, eligibility, onCheck }) {
  return <div className="order-detail"><div className="order-product"><div className="product-placeholder" aria-hidden="true"><span>RP</span></div><div><strong>Order {order.external_order_ref}</strong><span>{dateLabel(order.ordered_at)}</span></div></div><div className="order-facts"><div><span>Delivery</span><strong>{statusLabel(order.delivery_status)}</strong></div><div><span>Order ID</span><strong className="id-value">{order.order_id}</strong></div>{order.delivered_at && <div><span>Delivered</span><strong>{dateLabel(order.delivered_at)}</strong></div>}</div><div className="item-list"><h3>Items in this order</h3>{(order.items || []).map((item) => <article className="item-row" key={item.order_item_id}><div><strong>{item.product_name}</strong><span>SKU {item.sku} · Qty {item.quantity}</span>{item.condition_code && <span>Recorded condition: {statusLabel(item.condition_code)}</span>}</div><button className="text-button" onClick={() => onCheck(order.order_id, item.order_item_id)} disabled={eligibility?.loading}>Check eligibility</button></article>)}</div></div>
}

function ProposalCard({ proposal, decisionPending, onDecision, onViewRequest, onReconcile }) {
  const state = proposal.state
  if (state === 'declined') return <section className="proposal-card declined" aria-labelledby="proposal-title"><div className="card-heading"><div><p className="eyebrow">Decision recorded</p><h2 id="proposal-title">Proposal declined</h2></div><StatusBadge status="declined" /></div><p>Declined; no request was submitted.</p></section>
  if (state === 'expired') return <section className="proposal-card declined" aria-labelledby="proposal-title"><div className="card-heading"><div><p className="eyebrow">Decision unavailable</p><h2 id="proposal-title">Proposal expired</h2></div><StatusBadge status="expired" /></div><p>This proposal expired and can no longer be approved. No request was created.</p></section>
  if (state === 'completed' && proposal.request) return null
  if (state === 'checking') return <section className="proposal-card" aria-labelledby="proposal-title"><div className="card-heading"><div><p className="eyebrow">Outcome not yet confirmed</p><h2 id="proposal-title">Checking request status</h2></div><StatusBadge status="unconfirmed" /></div><p>Do not approve again while the outcome is unknown. Reconcile this proposal before retrying.</p><button className="button button-secondary" onClick={onReconcile}>Check proposal status</button></section>
  if (state !== 'pending') return null
  const snapshot = proposal.action_snapshot || {}
  return <section className="proposal-card" aria-labelledby="proposal-title"><div className="card-heading"><div><p className="eyebrow">Your decision is needed</p><h2 id="proposal-title">{statusLabel(snapshot.resolution)} proposal</h2></div><StatusBadge status="pending" /></div><div className="proposal-copy"><strong>Order item {snapshot.order_item_id}</strong><p>Action: {snapshot.resolution} for order {snapshot.order_id} (item {snapshot.order_item_id})</p>{Array.isArray(snapshot.conditions) && <ul>{snapshot.conditions.map((condition) => <li key={condition}>{condition}</li>)}</ul>}<p className="not-submitted">Nothing has been submitted yet. Approving creates one simulated request.</p></div><div className="proposal-actions"><button className="button button-primary" onClick={() => onDecision('approve')} disabled={decisionPending} aria-label={`Approve ${snapshot.resolution} proposal`}>{decisionPending ? 'Processing…' : `Approve ${snapshot.resolution}`}</button><button className="button button-secondary" onClick={() => onDecision('decline')} disabled={decisionPending}>Decline</button></div>{decisionPending && <p className="loading-line" role="status">Saving your decision…</p>}</section>
}

function RequestConfirmation({ request, onView }) {
  if (request.status === 'unconfirmed') return <section className="request-confirmation unconfirmed" aria-live="polite"><StatusBadge status="unconfirmed" /><h2>Outcome not yet confirmed</h2><p>Check request status before trying again. No success has been recorded in this screen.</p></section>
  return <section className="request-confirmation" aria-labelledby="request-confirmation-title"><div className="confirmation-check" aria-hidden="true">✓</div><div><p className="eyebrow">Persisted request</p><h2 id="request-confirmation-title">Your simulated request is confirmed</h2><p>The backend confirmed this request was saved.</p><dl><div><dt>Request ID</dt><dd>{request.request_id}</dd></div><div><dt>Status</dt><dd><StatusBadge status={request.status} /></dd></div><div><dt>Created</dt><dd>{dateLabel(request.created_at)}</dd></div></dl><button className="text-button" onClick={onView}>View request history →</button></div></section>
}

function StatusBadge({ status }) { return <span className={`status-badge status-${status}`}>{statusLabel(status)}</span> }

function ActivityTimeline({ events }) {
  return <section className="panel activity-panel" aria-labelledby="activity-title"><div className="card-heading"><div><p className="eyebrow">Observable activity</p><h2 id="activity-title">What happened</h2></div></div>{events.length === 0 ? <p className="muted">Tool calls and results will appear here when returned by the backend.</p> : <ol className="timeline">{events.map((event, index) => <li key={`${event.tool}-${index}`}><span className={`timeline-dot ${event.result?.error ? 'error' : ''}`} aria-hidden="true" /><div><strong>{toolLabel(event.tool)}</strong><span>{activityDetail(event)}</span></div></li>)}</ol>}</section>
}

function toolLabel(tool) {
  return ({ find_order: 'Order search', get_order_details: 'Order details retrieved', check_return_eligibility: 'Eligibility checked', unsupported: 'Unavailable operation' })[tool] || statusLabel(tool)
}

function activityDetail(event) {
  const result = event.result || {}
  if (result.error) return result.error.message || 'The check could not be completed.'
  if (Array.isArray(result.matches)) return `${result.matches.length} matching order${result.matches.length === 1 ? '' : 's'} returned.`
  if (result.order) return `Details returned for order ${result.order.external_order_ref || result.order.order_id}.`
  if (result.eligibility) return result.eligibility.eligible ? 'The backend marked this item eligible.' : 'The backend marked this item ineligible.'
  return 'Completed.'
}

function RequestHistoryPanel({ history }) {
  const request = history.request
  return <section className="panel history-result" aria-labelledby="history-result-title"><div className="card-heading"><div><p className="eyebrow">Persisted request record</p><h2 id="history-result-title">Request {request.request_id}</h2></div><StatusBadge status={request.status} /></div><dl className="history-facts"><div><dt>Current status</dt><dd>{statusLabel(request.status)}</dd></div><div><dt>Created</dt><dd>{dateLabel(request.created_at)}</dd></div><div><dt>Proposal</dt><dd className="id-value">{request.proposal_id}</dd></div></dl><h3>Recorded activity</h3>{history.events?.length ? <ol className="timeline">{history.events.map((event, index) => <li key={`${event.event_type}-${index}`}><span className="timeline-dot" aria-hidden="true" /><div><strong>{statusLabel(event.event_type)}</strong><span>{dateLabel(event.occurred_at)}{event.details?.status ? ` · ${statusLabel(event.details.status)}` : ''}{event.details?.decision ? ` · ${statusLabel(event.details.decision)}` : ''}</span></div></li>)}</ol> : <p className="muted">No activity events were returned.</p>}</section>
}
