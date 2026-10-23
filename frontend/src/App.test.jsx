import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from './App.jsx'
import { api, ApiError } from './api.js'

vi.mock('./api.js', async (importOriginal) => {
  const original = await importOriginal()
  return {
    ...original,
    api: {
      startDemoSession: vi.fn(),
      converse: vi.fn(),
      searchOrders: vi.fn(),
      getOrderDetails: vi.fn(),
      checkEligibility: vi.fn(),
      getProposal: vi.fn(),
      approveProposal: vi.fn(),
      declineProposal: vi.fn(),
      getRequestHistory: vi.fn(),
    },
  }
})

const pendingProposal = {
  proposal_id: 'proposal-1',
  order_id: 'order-1',
  order_item_id: 'item-1',
  state: 'pending',
  resolution: 'replacement',
  snapshot_version: 1,
  snapshot_hash: 'a'.repeat(64),
  action_snapshot: {
    snapshot_version: 1,
    order_id: 'order-1',
    order_item_id: 'item-1',
    resolution: 'replacement',
    conditions: ['Damaged item'],
  },
}

const order = {
  order_id: 'order-1',
  external_order_ref: 'RP-10001',
  ordered_at: '2026-01-02T00:00:00Z',
  delivery_status: 'delivered',
  items: [{ order_item_id: 'item-1', product_name: 'Demo mug', sku: 'MUG-1', quantity: 1 }],
}

function toolResult(result) {
  return { status: 'completed', reply: 'Here is the order information returned by the service.', tool_events: [{ tool: 'find_order', arguments: {}, result }], proposal: null }
}

async function sendMessage(message = 'Find order RP-10001') {
  await screen.findByText('Demo Customer')
  const composer = screen.getByRole('textbox', { name: 'Describe the order issue or ask a question' })
  fireEvent.change(composer, { target: { value: message } })
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }))
}

beforeEach(() => {
  api.startDemoSession.mockResolvedValue({ status: 'ready', display_name: 'Demo Customer' })
  api.converse.mockResolvedValue(toolResult({ order }))
})

afterEach(() => cleanup())

describe('customer workspace', () => {
  it('starts a credentialed demo session and submits a conversation with keyboard interaction', async () => {
    render(<App />)
    await screen.findByText('Demo Customer')
    expect(api.startDemoSession).toHaveBeenCalledOnce()
    const composer = screen.getByRole('textbox', { name: 'Describe the order issue or ask a question' })
    fireEvent.change(composer, { target: { value: 'Find order RP-10001' } })
    fireEvent.keyDown(composer, { key: 'Enter', shiftKey: false })
    await screen.findByText('Here is the order information returned by the service.')
    expect(api.converse).toHaveBeenCalledWith('Find order RP-10001')
    expect(screen.getByText('Demo mug')).toBeTruthy()
  })

  it('opens the Returns & replacements destination and marks it active', async () => {
    render(<App />)
    await screen.findByText('Demo Customer')
    const returnsNavigation = screen.getByRole('button', { name: 'Returns & replacements' })
    fireEvent.click(returnsNavigation)
    expect(screen.getByRole('heading', { name: 'Returns & replacements' })).toBeTruthy()
    expect(returnsNavigation.getAttribute('aria-current')).toBe('page')
    expect(screen.getByText(/Start with an order to check an item/)).toBeTruthy()
    expect(document.activeElement).toBe(screen.getByRole('region', { name: 'Returns & replacements' }))
  })

  it('opens Help at the conversation composer and marks it active', async () => {
    render(<App />)
    await screen.findByText('Demo Customer')
    const helpNavigation = screen.getByRole('button', { name: 'Help' })
    fireEvent.click(helpNavigation)
    expect(helpNavigation.getAttribute('aria-current')).toBe('page')
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Describe the order issue or ask a question' }))
  })

  it('uses authenticated order search and details for a unique header search result', async () => {
    api.searchOrders.mockResolvedValue({ matches: [order] })
    api.getOrderDetails.mockResolvedValue(order)
    render(<App />)
    await screen.findByText('Demo Customer')
    fireEvent.change(screen.getByRole('textbox', { name: 'Search orders by reference, product, or SKU' }), { target: { value: 'RP-10001' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search orders' }))
    expect(await screen.findByText('Demo mug')).toBeTruthy()
    expect(api.searchOrders).toHaveBeenCalledWith('RP-10001')
    expect(api.getOrderDetails).toHaveBeenCalledWith('order-1')
    expect(api.converse).not.toHaveBeenCalled()
  })

  it('lets the user select among multiple header search matches and shows details', async () => {
    const secondOrder = { ...order, order_id: 'order-2', external_order_ref: 'RP-10002' }
    api.searchOrders.mockResolvedValue({ matches: [order, secondOrder] })
    api.getOrderDetails.mockResolvedValue(secondOrder)
    render(<App />)
    await screen.findByText('Demo Customer')
    fireEvent.change(screen.getByRole('textbox', { name: 'Search orders by reference, product, or SKU' }), { target: { value: 'mug' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search orders' }))
    fireEvent.click(await screen.findByRole('button', { name: /RP-10002/ }))
    expect(await screen.findByText('order-2')).toBeTruthy()
    expect(api.getOrderDetails).toHaveBeenCalledWith('order-2')
    expect(api.converse).not.toHaveBeenCalled()
  })

  it('shows empty and failed header searches separately from conversation', async () => {
    api.searchOrders.mockResolvedValueOnce({ matches: [] }).mockRejectedValueOnce(new ApiError(503, 'service_unavailable', 'Search unavailable.'))
    render(<App />)
    await screen.findByText('Demo Customer')
    const searchInput = screen.getByRole('textbox', { name: 'Search orders by reference, product, or SKU' })
    fireEvent.change(searchInput, { target: { value: 'missing order' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search orders' }))
    expect(await screen.findByText(/No matching demo orders were found/)).toBeTruthy()
    fireEvent.change(searchInput, { target: { value: 'RP-10001' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search orders' }))
    expect((await screen.findByRole('alert')).textContent).toContain('temporarily unavailable')
    expect(api.converse).not.toHaveBeenCalled()
    expect(document.querySelector('.session-banner')).toBeNull()
    expect(screen.queryByText('Something went wrong. Please try again.')).toBeNull()
  })

  it('shows ambiguous order choices from structured tool results', async () => {
    const matches = [order, { ...order, order_id: 'order-2', external_order_ref: 'RP-10002' }]
    api.converse.mockResolvedValue(toolResult({ matches }))
    render(<App />)
    await screen.findByText('Demo Customer')
    fireEvent.change(screen.getByRole('textbox', { name: 'Describe the order issue or ask a question' }), { target: { value: 'Find my order' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))
    await screen.findByRole('heading', { name: 'Which order do you mean?' })
    fireEvent.click(screen.getByRole('button', { name: /Order RP-10002/ }))
    await waitFor(() => expect(api.converse).toHaveBeenLastCalledWith('The order is RP-10002.'))
  })

  it('removes ambiguity choices when the latest conversation turn returns a unique order', async () => {
    const matches = [order, { ...order, order_id: 'order-2', external_order_ref: 'RP-10002' }]
    api.converse.mockResolvedValueOnce(toolResult({ matches })).mockResolvedValueOnce(toolResult({ order }))
    render(<App />)
    await sendMessage('Find my order')
    await screen.findByRole('heading', { name: 'Which order do you mean?' })

    await sendMessage('Find RP-10001')
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Which order do you mean?' })).toBeNull())
    expect(screen.queryByRole('button', { name: /Order RP-10002/ })).toBeNull()
    expect(screen.getByText('Demo mug')).toBeTruthy()
  })

  it('renders proposal snapshot and confirms only the persisted request response', async () => {
    api.converse.mockResolvedValue({ ...toolResult({ order }), proposal: pendingProposal })
    api.approveProposal.mockResolvedValue({ request_id: 'request-42', proposal_id: 'proposal-1', status: 'submitted', created_at: '2026-01-03T00:00:00Z', outcome: 'confirmed' })
    render(<App />)
    await sendMessage()
    await screen.findByText('Replacement proposal')
    expect(screen.getByText('Damaged item')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Approve replacement proposal' }))
    await screen.findByText('Your simulated request is confirmed')
    expect(api.approveProposal).toHaveBeenCalledWith(expect.objectContaining({ snapshot_version: 1, snapshot_hash: 'a'.repeat(64) }))
    expect(screen.getByText('request-42')).toBeTruthy()
    expect(screen.getAllByText('Submitted').length).toBeGreaterThan(0)
  })

  it('clears the previous order proposal and request after selecting a different order', async () => {
    const secondOrder = { ...order, order_id: 'order-2', external_order_ref: 'RP-10002' }
    api.converse.mockResolvedValue({ ...toolResult({ order }), proposal: pendingProposal })
    api.approveProposal.mockResolvedValue({ request_id: 'request-42', proposal_id: 'proposal-1', status: 'submitted', created_at: '2026-01-03T00:00:00Z', outcome: 'confirmed' })
    api.searchOrders.mockResolvedValue({ matches: [secondOrder] })
    api.getOrderDetails.mockResolvedValue(secondOrder)
    render(<App />)
    await sendMessage()
    await screen.findByText('Replacement proposal')
    fireEvent.click(screen.getByRole('button', { name: 'Approve replacement proposal' }))
    await screen.findByText('Your simulated request is confirmed')

    fireEvent.change(screen.getByRole('textbox', { name: 'Search orders by reference, product, or SKU' }), { target: { value: 'RP-10002' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search orders' }))
    expect(await screen.findByText('order-2')).toBeTruthy()
    expect(screen.queryByText('Replacement proposal')).toBeNull()
    expect(screen.queryByText('Your simulated request is confirmed')).toBeNull()
    expect(screen.getByText(/Start with an order to check an item/)).toBeTruthy()
  })

  it('declines through the API and does not create a request', async () => {
    api.converse.mockResolvedValue({ ...toolResult({ order }), proposal: pendingProposal })
    api.declineProposal.mockResolvedValue({ proposal_id: 'proposal-1', state: 'declined', decision: 'declined' })
    render(<App />)
    await sendMessage()
    await screen.findByText('Replacement proposal')
    fireEvent.click(screen.getByRole('button', { name: 'Decline' }))
    await screen.findByText('Proposal declined')
    expect(api.declineProposal).toHaveBeenCalledOnce()
    expect(api.approveProposal).not.toHaveBeenCalled()
    expect(screen.queryByText('Your simulated request is confirmed')).toBeNull()
  })

  it('renders expired proposals as terminal and without approval controls', async () => {
    api.converse.mockResolvedValue({ ...toolResult({ order }), proposal: { ...pendingProposal, state: 'expired' } })
    render(<App />)
    await sendMessage()
    const expiredProposal = await screen.findByRole('region', { name: 'Proposal expired' })
    expect(expiredProposal.textContent).toContain('can no longer be approved')
    expect(expiredProposal.textContent).toContain('No request was created')
    expect(screen.queryByRole('button', { name: 'Approve replacement proposal' })).toBeNull()
    expect(screen.queryByText('Your simulated request is confirmed')).toBeNull()
    expect(api.approveProposal).not.toHaveBeenCalled()
  })

  it('renders proposal action identifiers and terms only from the persisted snapshot', async () => {
    const conflictingProposal = {
      ...pendingProposal,
      order_id: 'other-order',
      order_item_id: 'other-item',
      resolution: 'refund',
      action_snapshot: {
        ...pendingProposal.action_snapshot,
        order_id: 'snapshot-order',
        order_item_id: 'snapshot-item',
        resolution: 'replacement',
        conditions: ['Snapshot condition'],
      },
    }
    api.converse.mockResolvedValue({ ...toolResult({ order }), proposal: conflictingProposal })
    render(<App />)
    await sendMessage()
    const proposalCard = await screen.findByRole('region', { name: 'Replacement proposal' })
    expect(proposalCard.textContent).toContain('snapshot-order')
    expect(proposalCard.textContent).toContain('snapshot-item')
    expect(proposalCard.textContent).toContain('Snapshot condition')
    expect(proposalCard.textContent).not.toContain('other-order')
    expect(proposalCard.textContent).not.toContain('other-item')
    expect(proposalCard.textContent).not.toContain('refund')
    expect(proposalCard.textContent).not.toContain('Demo mug')
  })

  it('shows provider failure as an error without claiming a successful conversation', async () => {
    api.converse.mockRejectedValue(new ApiError(503, 'provider_unavailable', 'Provider unavailable.'))
    render(<App />)
    await sendMessage('Find an order')
    expect((await screen.findByRole('alert')).textContent).toContain('temporarily unavailable')
    expect(document.querySelector('.session-banner')).toBeNull()
    expect(screen.queryByText('Your simulated request is confirmed')).toBeNull()
  })

  it('clears a failed session-start banner and restores the workspace after retry', async () => {
    api.startDemoSession
      .mockRejectedValueOnce(new ApiError(503, 'session_unavailable', 'Session unavailable.'))
      .mockResolvedValueOnce({ status: 'ready', display_name: 'Demo Customer' })
    render(<App />)
    expect((await screen.findByRole('alert')).textContent).toContain('temporarily unavailable')
    fireEvent.click(screen.getAllByRole('button', { name: 'Request history' })[0])
    expect(screen.getByRole('heading', { name: 'Request history' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Start demo session' }))
    await screen.findByText('Demo Customer')
    expect(await screen.findByRole('heading', { name: 'How can we help with an order?' })).toBeTruthy()
    expect(document.querySelector('.session-banner')).toBeNull()
    expect(screen.getByRole('textbox', { name: 'Describe the order issue or ask a question' }).disabled).toBe(false)
  })

  it('offers a fresh demo session after an authenticated request expires', async () => {
    api.converse.mockRejectedValue(new ApiError(401, 'not_authenticated', 'expired'))
    render(<App />)
    await sendMessage('Find an order')
    expect((await screen.findAllByText('Your demo session ended. Start a new demo session to continue.')).length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: 'Start demo session' }))
    await waitFor(() => expect(api.startDemoSession).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('renders persisted request status and activity returned by the API', async () => {
    api.getRequestHistory.mockResolvedValue({
      request: { request_id: 'request-42', proposal_id: 'proposal-1', status: 'submitted', created_at: '2026-01-03T00:00:00Z' },
      events: [{ event_type: 'request_created', occurred_at: '2026-01-03T00:00:00Z', details: { status: 'submitted' } }],
    })
    render(<App />)
    await screen.findByText('Demo Customer')
    fireEvent.click(screen.getAllByRole('button', { name: 'Request history' })[0])
    fireEvent.change(screen.getByRole('textbox', { name: 'Request ID' }), { target: { value: 'request-42' } })
    fireEvent.click(screen.getByRole('button', { name: 'View request' }))
    expect(await screen.findByText('Request created')).toBeTruthy()
    expect(screen.getAllByText('Submitted').length).toBeGreaterThan(0)
  })

  it('offers status reconciliation after an unconfirmed approval outcome', async () => {
    api.converse.mockResolvedValue({ ...toolResult({ order }), proposal: pendingProposal })
    api.approveProposal.mockResolvedValue({ proposal_id: 'proposal-1', status: 'unconfirmed' })
    api.getProposal.mockRejectedValue(new Error('not reachable'))
    render(<App />)
    await sendMessage()
    await screen.findByText('Replacement proposal')
    fireEvent.click(screen.getByRole('button', { name: 'Approve replacement proposal' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Check proposal status' }))
    await waitFor(() => expect(api.getProposal).toHaveBeenCalledWith('proposal-1'))
    expect(await screen.findByText('The outcome is still unconfirmed. Check the proposal status again before retrying.')).toBeTruthy()
    expect(screen.queryByText('Your simulated request is confirmed')).toBeNull()
  })
})
