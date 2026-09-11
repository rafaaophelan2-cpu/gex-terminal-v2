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

export async function fetchVix() {
  const resp = await fetch(`${API_BASE}/market/vix`, { credentials: 'include' })
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  return resp.json()
}

export async function fetchExpirations(symbol) {
  const resp = await fetch(`${API_BASE}/market/expirations?symbol=${encodeURIComponent(symbol)}`, {
    credentials: 'include',
  })
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  const data = await resp.json()
  return data.expirations
}

export async function fetchGammaGrid(symbol, expKeys) {
  const params = new URLSearchParams({ symbol })
  if (expKeys && expKeys.length > 0) params.set('exp_keys', expKeys.join(','))
  const resp = await fetch(`${API_BASE}/market/gamma-grid?${params.toString()}`, {
    credentials: 'include',
  })
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}))
    throw new Error(detail.detail || `Error ${resp.status}`)
  }
  return resp.json()
}

export async function postAiDiagnosis(symbol, tipoAnalisis) {
  const resp = await fetch(`${API_BASE}/market/ai-diagnosis`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, tipo_analisis: tipoAnalisis }),
  })
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}))
    throw new Error(detail.detail || `Error ${resp.status}`)
  }
  return resp.json()
}
