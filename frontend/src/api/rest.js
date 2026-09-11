import { API_BASE } from '../config.js'

export async function fetchDrift(symbol, date) {
  const params = new URLSearchParams({ symbol })
  if (date) params.set('date', date)
  const resp = await fetch(`${API_BASE}/market/drift?${params.toString()}`, {
    credentials: 'include',
  })
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  return resp.json()
}

export async function fetchHeatmap(symbol, date) {
  const params = new URLSearchParams({ symbol })
  if (date) params.set('date', date)
  const resp = await fetch(`${API_BASE}/market/heatmap?${params.toString()}`, {
    credentials: 'include',
  })
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  return resp.json()
}
