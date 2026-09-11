import { apiFetch } from './http.js'

export async function fetchChatHistory() {
  const resp = await apiFetch('/chat/history')
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  const data = await resp.json()
  return data.messages
}

export async function postChatMessage(symbol, message) {
  const resp = await apiFetch('/chat/message', {
    method: 'POST',
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
  const resp = await apiFetch('/chat/history', { method: 'DELETE' })
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
}
