const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message || 'The request could not be completed.')
    this.name = 'ApiError'
    this.status = status
    this.code = code || 'request_failed'
  }
}

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      credentials: 'include',
      headers: {
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
    })
  } catch {
    throw new ApiError(0, 'network_error', 'The service could not be reached. Check the connection and try again.')
  }

  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = body?.detail
    const code = typeof detail === 'object' ? detail.code : `http_${response.status}`
    const message = typeof detail === 'object' ? detail.message : typeof detail === 'string' ? detail : null
    throw new ApiError(response.status, code, message)
  }
  return body
}

const json = (method, payload) => ({ method, body: JSON.stringify(payload) })

export const api = {
  startDemoSession: () => request('/api/demo/session', json('POST', {})),
  converse: (message) => request('/api/conversation', json('POST', { message })),
  searchOrders: (query) => request(`/api/orders?${new URLSearchParams({ query: query.trim() })}`),
  getOrderDetails: (orderId) => request(`/api/orders/${encodeURIComponent(orderId)}`),
  checkEligibility: (orderId, itemId) => request(`/api/orders/${orderId}/items/${itemId}/eligibility`),
  getProposal: (proposalId) => request(`/api/proposals/${proposalId}`),
  approveProposal: (proposal) => request(
    `/api/proposals/${proposal.proposal_id}/approve`,
    json('POST', { snapshot_version: proposal.snapshot_version, snapshot_hash: proposal.snapshot_hash }),
  ),
  declineProposal: (proposal) => request(
    `/api/proposals/${proposal.proposal_id}/decline`,
    json('POST', { snapshot_version: proposal.snapshot_version, snapshot_hash: proposal.snapshot_hash }),
  ),
  getRequest: (requestId) => request(`/api/requests/${encodeURIComponent(requestId)}`),
  getRequestHistory: (requestId) => request(`/api/requests/${encodeURIComponent(requestId)}/history`),
}

export function errorMessage(error) {
  if (!(error instanceof ApiError)) return 'Something went wrong. Please try again.'
  if (error.status === 401) return 'Your demo session ended. Start a new demo session to continue.'
  if (error.status === 403) return 'This action is not available for this demo account.'
  if (error.status === 404) return 'That order or request could not be found in this demo account.'
  if (error.status === 409) return 'The proposal changed or is no longer pending. Refresh its status before deciding.'
  if (error.status === 503) return 'The assistant or service is temporarily unavailable. Your request was not confirmed.'
  return error.message || 'Something went wrong. Please try again.'
}

export function isAuthenticationError(error) {
  return error instanceof ApiError && error.status === 401
}
