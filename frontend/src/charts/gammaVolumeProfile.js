import Plotly from 'plotly.js-dist-min'
import { COLOR_BG, COLOR_NEGATIVE, COLOR_POSITIVE } from '../theme.js'
import { fmtMoney } from '../utils/format.js'

/** Volume profile de gamma: una barra horizontal por strike, con el Net
 * GEX real SUMADO a través de todas las expiraciones seleccionadas en
 * el GRID (a diferencia del color de cada celda de la tabla, que usa un
 * peso normalizado por DTE -- acá la pregunta es "¿cuánto gamma total
 * hay en este strike entre todo lo elegido?", no "qué tan fuerte se ve
 * cada celda"). Verde para niveles netos positivos, rojo para negativos
 * -- a diferencia de la referencia visual del usuario (magenta/cian),
 * se mantiene la misma convención de color que el resto de la app. */
export function renderGammaVolumeProfile(el, grid) {
  if (!grid.strikes || grid.strikes.length === 0) {
    el.innerHTML = ''
    return
  }

  const rows = grid.strikes
    .map((strike, idx) => ({ strike, total: grid.values[idx].reduce((a, b) => a + b, 0) }))
    .sort((a, b) => a.strike - b.strike)

  const strikes = rows.map((r) => String(r.strike))
  const totals = rows.map((r) => r.total)
  const colors = totals.map((v) => (v >= 0 ? COLOR_POSITIVE : COLOR_NEGATIVE))

  const trace = {
    type: 'bar',
    orientation: 'h',
    x: totals,
    y: strikes,
    marker: { color: colors },
    text: totals.map((v) => fmtMoney(v)),
    textposition: 'outside',
    textfont: { size: 9 },
    hovertemplate: 'Strike: $%{y}<br>Net GEX total: %{x:,.0f}<extra></extra>',
  }

  const layout = {
    plot_bgcolor: COLOR_BG,
    paper_bgcolor: COLOR_BG,
    font: { color: '#D1D5DB', family: 'JetBrains Mono, monospace', size: 10 },
    title: { text: 'Gamma Volume Profile', font: { color: '#F0F6FC', size: 12 } },
    xaxis: { gridcolor: 'rgba(255,255,255,0.05)', zeroline: true, zerolinecolor: 'rgba(255,255,255,0.15)' },
    yaxis: { type: 'category', gridcolor: 'rgba(255,255,255,0.03)', automargin: true },
    margin: { l: 50, r: 55, t: 36, b: 26 },
    showlegend: false,
    hoverlabel: {
      font: { family: 'JetBrains Mono, monospace', size: 12, color: '#F0F6FC' },
      bgcolor: '#0E131F',
      bordercolor: 'rgba(255,255,255,0.15)',
    },
  }

  Plotly.react(el, [trace], layout, { responsive: true, displaylogo: false })
}
