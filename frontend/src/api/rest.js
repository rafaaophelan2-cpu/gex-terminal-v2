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

export async function fetchCandles(symbol, date) {
  const params = new URLSearchParams({ symbol })
  if (date) params.set('date', date)
  const resp = await fetch(`${API_BASE}/market/candles?${params.toString()}`, {
    credentials: 'include',
  })
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  return resp.json()
}

export async function fetchAvailableDates(symbol) {
  const resp = await fetch(`${API_BASE}/market/available-dates?symbol=${encodeURIComponent(symbol)}`, {
    credentials: 'include',
  })
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  const data = await resp.json()
  return data.dates
}
