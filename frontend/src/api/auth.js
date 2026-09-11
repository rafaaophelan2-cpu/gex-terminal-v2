import { API_BASE } from '../config.js'

export async function login(username, password) {
  const resp = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ username, password }),
  })
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) {
    throw new Error(data.detail || `Error ${resp.status}`)
  }
  return data
}

export async function logout() {
  await fetch(`${API_BASE}/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  })
}

export async function me() {
  const resp = await fetch(`${API_BASE}/auth/me`, {
    credentials: 'include',
  })
  if (!resp.ok) return null
  return resp.json()
}
