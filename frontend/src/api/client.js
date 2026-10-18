// Thin API client on top of fetch. Holds the JWT and exposes typed-ish
// helpers. On 409 (conflict) it surfaces the server's current-version header
// so the UI can show "this item changed, reload".

const BASE = import.meta.env.VITE_API_URL || ''

const TOKEN_KEY = 'opsflow_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  constructor(status, message, headers) {
    super(message)
    this.status = status
    this.headers = headers
  }
}

async function request(path, { method = 'GET', body, headers = {}, idempotencyKey } = {}) {
  const finalHeaders = { ...headers }
  if (body) finalHeaders['Content-Type'] = 'application/json'
  const token = getToken()
  if (token) finalHeaders['Authorization'] = `Bearer ${token}`
  if (idempotencyKey) finalHeaders['Idempotency-Key'] = idempotencyKey

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: finalHeaders,
    body: body ? JSON.stringify(body) : undefined,
  })

  // 204 has no body; 401 should clear the token.
  let data = null
  const text = await res.text()
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = { detail: text }
    }
  }

  if (!res.ok) {
    if (res.status === 401) setToken(null)
    const message =
      (data && (data.detail || data.message)) ||
      `Request failed (${res.status})`
    throw new ApiError(res.status, message, res.headers)
  }
  return data
}

export const api = {
  login: (email, password) =>
    request('/auth/login', { method: 'POST', body: { email, password } }),
  me: () => request('/auth/me'),
  // work items
  listItems: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    return request(`/items?${qs.toString()}`)
  },
  getItem: (id) => request(`/items/${id}`),
  createItem: (payload, idempotencyKey) =>
    request('/items', { method: 'POST', body: payload, idempotencyKey }),
  updateItem: (id, payload) =>
    request(`/items/${id}`, { method: 'PATCH', body: payload }),
  claimItem: (id) => request(`/items/${id}/claim`, { method: 'POST' }),
  assignItem: (id, assigneeId) =>
    request(`/items/${id}/assign`, { method: 'POST', body: { assignee_id: assigneeId } }),
  transitionItem: (id, targetStatus) =>
    request(`/items/${id}/transition`, { method: 'POST', body: { target_status: targetStatus } }),
  addComment: (id, body) =>
    request(`/items/${id}/comments`, { method: 'POST', body: { body } }),
  getActivity: (id, page = 1) =>
    request(`/items/${id}/activity?page=${page}`),
  dashboard: () => request('/dashboard'),
}
