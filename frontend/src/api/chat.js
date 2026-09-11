import { API_BASE } from '../config.js'

export async function fetchChatHistory() {
  const resp = await fetch(`${API_BASE}/chat/history`, { credentials: 'include' })
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  const data = await resp.json()
  return data.messages
}

export async function postChatMessage(symbol, message) {
  const resp = await fetch(`${API_BASE}/chat/message`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, message }),
  })
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}))
    throw new Error(detail.detail || `Error ${resp.status}`)
  }
  return resp.json()
}

export async function clearChatHistory() {
  const resp = await fetch(`${API_BASE}/chat/history`, {
    method: 'DELETE',
    credentials: 'include',
  })
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
}
