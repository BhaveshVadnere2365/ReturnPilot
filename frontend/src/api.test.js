import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, errorMessage, isAuthenticationError } from './api.js'

afterEach(() => vi.unstubAllGlobals())

describe('API client', () => {
  it('sends credentialed JSON requests for the HttpOnly demo session', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'ready' }) })
    vi.stubGlobal('fetch', fetchMock)
    await api.startDemoSession()
    expect(fetchMock).toHaveBeenCalledWith('/api/demo/session', expect.objectContaining({
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
    }))
  })

  it('uses the authenticated order search and details endpoints with encoded input', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ matches: [] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ order_id: 'order-1' }) })
    vi.stubGlobal('fetch', fetchMock)
    await api.searchOrders('RP 10001 /')
    await api.getOrderDetails('order/1')
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/orders?query=RP+10001+%2F', expect.objectContaining({ credentials: 'include' }))
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/orders/order%2F1', expect.objectContaining({ credentials: 'include' }))
  })

  it.each([
    [401, 'session ended'],
    [403, 'not available'],
    [404, 'could not be found'],
    [409, 'no longer pending'],
    [503, 'temporarily unavailable'],
  ])('maps HTTP %i to a safe user message', async (status, phrase) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status,
      json: async () => ({ detail: { code: 'safe_code', message: 'safe public text' } }),
    }))
    const error = await api.converse('synthetic query').catch((reason) => reason)
    expect(error).toMatchObject({ status })
    expect(errorMessage(error)).toContain(phrase)
  })

  it('classifies only unauthorized API responses as session errors', () => {
    expect(isAuthenticationError(new ApiError(401, 'not_authenticated'))).toBe(true)
    expect(isAuthenticationError(new ApiError(503, 'provider_unavailable'))).toBe(false)
    expect(isAuthenticationError(new ApiError(503, 'service_unavailable'))).toBe(false)
    expect(isAuthenticationError(new Error('failure'))).toBe(false)
  })
})
