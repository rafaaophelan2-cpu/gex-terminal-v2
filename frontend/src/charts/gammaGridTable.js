import { COLOR_NEGATIVE, COLOR_POSITIVE } from '../theme.js'
import { fmtMoney } from '../utils/format.js'

/** GRID: tabla strike x expiración con Net GEX real por celda, coloreada
 * en degradado verde/rojo. A diferencia de un heatmap de Plotly, esto es
 * una tabla HTML real -- permite mostrar el monto exacto como texto
 * DENTRO de cada celda (igual que la referencia del usuario), cosa que
 * un heatmap de Plotly no hace bien a esta densidad.
 *
 * El color de cada celda NO usa el monto real (grid.values) sino el peso
 * ya normalizado por DTE que manda el backend (grid.weights, ver
 * domain/gamma_grid.py): el mismo monto en USD pesa menos cuanto más
 * lejos está la expiración (gamma ~ 1/sqrt(T) en Black-Scholes), así que
 * un nivel de 10M a 0DTE se ve más intenso que uno de 10M a 10DTE,
 * aunque el texto de la celda muestre el mismo número real. */
function colorForWeight(weight, maxAbsWeight) {
  if (!maxAbsWeight || weight === 0) return 'transparent'
  const t = Math.max(-1, Math.min(1, weight / maxAbsWeight))
  const alpha = Math.abs(t) * 0.7
  const [r, g, b] = t >= 0 ? hexToRgb(COLOR_POSITIVE) : hexToRgb(COLOR_NEGATIVE)
  return `rgba(${r}, ${g}, ${b}, ${alpha.toFixed(3)})`
}

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function formatColumnHeader(col) {
  const [year, month, day] = col.exp_date.split('-')
  return `${day}/${month}/${year.slice(2)}<br><span class="grid-col-dte">${col.dte} DTE</span>`
}

export function renderGammaGridTable(el, grid) {
  if (!grid.strikes || grid.strikes.length === 0 || !grid.columns || grid.columns.length === 0) {
    el.innerHTML = '<p class="grid-placeholder">Sin datos para las expiraciones seleccionadas.</p>'
    return
  }

  // Strikes de mayor a menor (como una escalera de precios) -- hay que
  // recorrer los índices en ese orden ya que grid.values viene ordenado
  // de menor a mayor strike (ver compute_gamma_grid).
  const rowOrder = grid.strikes
    .map((strike, idx) => ({ strike, idx }))
    .sort((a, b) => b.strike - a.strike)

  let html = '<table class="gamma-grid-table"><thead><tr><th class="grid-strike-col">Strike</th>'
  for (const col of grid.columns) {
    html += `<th>${formatColumnHeader(col)}</th>`
  }
  html += '</tr></thead><tbody>'

  for (const { strike, idx } of rowOrder) {
    html += `<tr><td class="grid-strike-col">${strike % 1 === 0 ? strike.toFixed(0) : strike.toFixed(2)}</td>`
    for (let c = 0; c < grid.columns.length; c++) {
      const value = grid.values[idx][c]
      const weight = grid.weights[idx][c]
      const bg = colorForWeight(weight, grid.max_abs_weight)
      html += `<td style="background:${bg}" title="Strike $${strike} · ${grid.columns[c].exp_date} (${grid.columns[c].dte} DTE): ${fmtMoney(value)}">${value !== 0 ? fmtMoney(value) : ''}</td>`
    }
    html += '</tr>'
  }

  html += '<tr class="grid-net-row"><td class="grid-strike-col">NET</td>'
  for (let c = 0; c < grid.columns.length; c++) {
    const net = grid.net_by_column[c]
    const cls = net >= 0 ? 'val-positive' : 'val-negative'
    html += `<td class="${cls}">${fmtMoney(net)}</td>`
  }
  html += '</tr>'

  html += '</tbody></table>'

  el.innerHTML = html
}
