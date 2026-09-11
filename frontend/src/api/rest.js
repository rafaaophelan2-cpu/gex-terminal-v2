import { API_BASE } from '../config.js'

export async function fetchDrift(symbol) {
  const resp = await fetch(`${API_BASE}/market/drift?symbol=${encodeURIComponent(symbol)}`, {
    credentials: 'include',
  })
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  return resp.json()
}
