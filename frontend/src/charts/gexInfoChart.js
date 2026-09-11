import Plotly from 'plotly.js-dist-min'
import { COLOR_ACCENT, COLOR_BG, COLOR_NEGATIVE, COLOR_POSITIVE } from '../theme.js'

// Un solo gráfico de GEX INFO en esta pantalla (Fase 2 MVP) -- si más
// adelante hay varias instancias en pantalla a la vez, esto pasa a ser
// estado por elemento (ej. un WeakMap<HTMLElement, boolean>).
let initialized = false

function spotLineShape(spot) {
  if (!spot) return []
  return [{
    type: 'line', x0: spot, x1: spot, y0: 0, y1: 1, yref: 'paper',
    line: { color: COLOR_ACCENT, width: 1.5, dash: 'dash' },
  }]
}

function baseLayout(spot) {
  return {
    plot_bgcolor: COLOR_BG,
    paper_bgcolor: COLOR_BG,
    font: { color: '#D1D5DB', family: 'JetBrains Mono, monospace', size: 11 },
    title: { text: 'Net GEX Profile', font: { color: '#F0F6FC', size: 15 } },
    xaxis: { title: 'Strike ($)', gridcolor: 'rgba(255,255,255,0.05)', zeroline: false },
    yaxis: {
      title: 'Net GEX ($)', gridcolor: 'rgba(255,255,255,0.05)',
      zeroline: true, zerolinecolor: 'rgba(255,255,255,0.15)',
    },
    shapes: spotLineShape(spot),
    margin: { l: 70, r: 30, t: 50, b: 50 },
    height: 600,
    showlegend: false,
  }
}

/** Redibuja la estructura completa (Plotly.react) -- solo al recibir
 * 'chain_full' (cambio de símbolo/DTE/strike-range), nunca en cada tick. */
export function renderChainFull(el, payload, spot) {
  const strikes = payload.by_strike.map((s) => s.strike)
  const netGex = payload.by_strike.map((s) => s.net_gex)
  const colors = netGex.map((v) => (v >= 0 ? COLOR_POSITIVE : COLOR_NEGATIVE))

  const trace = {
    type: 'bar',
    x: strikes,
    y: netGex,
    marker: { color: colors },
    hovertemplate: 'Strike: $%{x}<br>Net GEX: %{y:,.0f}<extra></extra>',
  }

  if (!initialized) {
    Plotly.newPlot(el, [trace], baseLayout(spot), { responsive: true, displaylogo: false })
    initialized = true
  } else {
    Plotly.react(el, [trace], baseLayout(spot), { responsive: true, displaylogo: false })
  }
}

/** Actualización liviana (Plotly.restyle/relayout) en cada 'tick' -- nunca
 * newPlot/react acá, es justo lo que evita el parpadeo. */
export function updateTick(el, payload, spot) {
  if (!initialized) {
    renderChainFull(el, payload, spot)
    return
  }
  const strikes = payload.by_strike.map((s) => s.strike)
  const netGex = payload.by_strike.map((s) => s.net_gex)
  const colors = netGex.map((v) => (v >= 0 ? COLOR_POSITIVE : COLOR_NEGATIVE))

  Plotly.restyle(el, { x: [strikes], y: [netGex], 'marker.color': [colors] })
  Plotly.relayout(el, { shapes: spotLineShape(spot) })
}

export function resetGexInfoChart() {
  initialized = false
}
