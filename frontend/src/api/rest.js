import { apiFetch } from './http.js'

export async function fetchDrift(symbol, date, otmOnly = false, mode = 'gex') {
  const params = new URLSearchParams({ symbol })
  if (date) params.set('date', date)
  if (otmOnly) params.set('otm_only', 'true')
  if (mode && mode !== 'gex') params.set('mode', mode)
  const resp = await apiFetch(`/market/drift?${params.toString()}`)
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  return resp.json()
}

export async function fetchHeatmap(symbol, date) {
  const params = new URLSearchParams({ symbol })
  if (date) params.set('date', date)
  const resp = await apiFetch(`/market/heatmap?${params.toString()}`)
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  return resp.json()
}

export async function fetchCharmHeatmap(symbol, date) {
  const params = new URLSearchParams({ symbol })
  if (date) params.set('date', date)
  const resp = await apiFetch(`/market/heatmap-charm?${params.toString()}`)
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  return resp.json()
}

export async function fetchCandles(symbol, date) {
  const params = new URLSearchParams({ symbol })
  if (date) params.set('date', date)
  const resp = await apiFetch(`/market/candles?${params.toString()}`)
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  return resp.json()
}

export async function fetchAvailableDates(symbol) {
  const resp = await apiFetch(`/market/available-dates?symbol=${encodeURIComponent(symbol)}`)
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  const data = await resp.json()
  return data.dates
}

export async function fetchVix() {
  const resp = await apiFetch('/market/vix')
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  return resp.json()
}

export async function fetchVixTermStructure() {
  const resp = await apiFetch('/market/vix-term-structure')
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  return resp.json()
}

export async function fetchImpliedRange(symbol) {
  const resp = await apiFetch(`/market/implied-range?symbol=${encodeURIComponent(symbol)}`)
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  return resp.json()
}

export async function fetchCompoundedLevels(symbol) {
  const resp = await apiFetch(`/market/compounded-levels?symbol=${encodeURIComponent(symbol)}`)
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  return resp.json()
}

export async function fetchTradingViewString(symbol) {
  const resp = await apiFetch(`/market/tradingview-string?symbol=${encodeURIComponent(symbol)}`)
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  return resp.json()
}

export async function fetchExpirations(symbol) {
  const resp = await apiFetch(`/market/expirations?symbol=${encodeURIComponent(symbol)}`)
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  const data = await resp.json()
  return data.expirations
}

export async function fetchGammaGrid(symbol, expKeys) {
  const params = new URLSearchParams({ symbol })
  if (expKeys && expKeys.length > 0) params.set('exp_keys', expKeys.join(','))
  const resp = await apiFetch(`/market/gamma-grid?${params.toString()}`)
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}))
    throw new Error(detail.detail || `Error ${resp.status}`)
  }
  return resp.json()
}

export async function fetchGammaSurface(symbol, expKeys) {
  const params = new URLSearchParams({ symbol })
  if (expKeys && expKeys.length > 0) params.set('exp_keys', expKeys.join(','))
  const resp = await apiFetch(`/market/gamma-surface?${params.toString()}`)
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}))
    throw new Error(detail.detail || `Error ${resp.status}`)
  }
  return resp.json()
}

export async function fetchVolSurface(symbol, expKeys) {
  const params = new URLSearchParams({ symbol })
  if (expKeys && expKeys.length > 0) params.set('exp_keys', expKeys.join(','))
  const resp = await apiFetch(`/market/vol-surface?${params.toString()}`)
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}))
    throw new Error(detail.detail || `Error ${resp.status}`)
  }
  return resp.json()
}

export async function fetchEconomicCalendar() {
  const resp = await apiFetch('/market/economic-calendar')
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  const data = await resp.json()
  return data.events
}

export async function fetchNews() {
  const resp = await apiFetch('/market/news')
  if (!resp.ok) throw new Error(`Error ${resp.status}`)
  const data = await resp.json()
  return data.articles
}

export async function postAiDiagnosis(symbol, tipoAnalisis, conversionRatio) {
  const resp = await apiFetch('/market/ai-diagnosis', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, tipo_analisis: tipoAnalisis, conversion_ratio: conversionRatio || null }),
  })
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}))
    throw new Error(detail.detail || `Error ${resp.status}`)
  }
  return resp.json()
}
