import Plotly from 'plotly.js-dist-min'
import { COLOR_ACCENT, COLOR_BG, COLOR_NEGATIVE, COLOR_POSITIVE } from '../theme.js'
import { strongestOutline } from '../utils/chartHighlight.js'

// 'net' | 'callput' | null -- a diferencia del 'initialized' booleano
// anterior, hace falta saber en qué MODO se inicializó el gráfico: el
// modo 'net' dibuja 1 traza, 'callput' dibuja 2 (call/put agrupadas por
// strike) -- restyle() asume que la cantidad de trazas no cambia entre
// llamadas, así que un cambio de modo necesita un redibujado completo
// (Plotly.react), no un restyle liviano.
let initializedMode = null

function spotLineShape(spot) {
  if (!spot) return []
  return [{
    type: 'line', x0: spot, x1: spot, y0: 0, y1: 1, yref: 'paper',
    line: { color: COLOR_ACCENT, width: 1.5, dash: 'dash' },
  }]
}

function baseLayout(spot, viewMode) {
  const isCallPut = viewMode === 'callput'
  return {
    plot_bgcolor: COLOR_BG,
    paper_bgcolor: COLOR_BG,
    font: { color: '#D1D5DB', family: 'JetBrains Mono, monospace', size: 11 },
    title: { text: isCallPut ? 'Call vs Put GEX Profile' : 'Net GEX Profile', font: { color: '#F0F6FC', size: 15 } },
    xaxis: { title: 'Strike ($)', gridcolor: 'rgba(255,255,255,0.05)', zeroline: false },
    yaxis: {
      title: isCallPut ? 'GEX ($)' : 'Net GEX ($)', gridcolor: 'rgba(255,255,255,0.05)',
      zeroline: true, zerolinecolor: 'rgba(255,255,255,0.15)',
    },
    barmode: isCallPut ? 'group' : undefined,
    shapes: spotLineShape(spot),
    hoverlabel: {
      font: { family: 'JetBrains Mono, monospace', size: 12, color: '#F0F6FC' },
      bgcolor: '#0E131F',
      bordercolor: 'rgba(255,255,255,0.15)',
    },
    margin: { l: 70, r: 30, t: 50, b: 50 },
    height: 600,
    showlegend: isCallPut,
    legend: isCallPut ? { orientation: 'h', y: 1.08, font: { size: 10 } } : undefined,
  }
}

function buildTraces(payload, viewMode) {
  const strikes = payload.by_strike.map((s) => s.strike)

  if (viewMode === 'callput') {
    const callGex = payload.by_strike.map((s) => s.call_gex)
    const putGex = payload.by_strike.map((s) => s.put_gex)
    const callOutline = strongestOutline(callGex)
    const putOutline = strongestOutline(putGex)
    return [
      {
        type: 'bar', name: 'Calls', x: strikes, y: callGex,
        marker: { color: COLOR_POSITIVE, line: { color: callOutline.colors, width: callOutline.widths } },
        hovertemplate: 'Strike: $%{x}<br>Call GEX: %{y:,.0f}<extra></extra>',
      },
      {
        type: 'bar', name: 'Puts', x: strikes, y: putGex,
        marker: { color: COLOR_NEGATIVE, line: { color: putOutline.colors, width: putOutline.widths } },
        hovertemplate: 'Strike: $%{x}<br>Put GEX: %{y:,.0f}<extra></extra>',
      },
    ]
  }

  const netGex = payload.by_strike.map((s) => s.net_gex)
  const colors = netGex.map((v) => (v >= 0 ? COLOR_POSITIVE : COLOR_NEGATIVE))
  const outline = strongestOutline(netGex)
  return [{
    type: 'bar',
    x: strikes,
    y: netGex,
    marker: { color: colors, line: { color: outline.colors, width: outline.widths } },
    hovertemplate: 'Strike: $%{x}<br>Net GEX: %{y:,.0f}<extra></extra>',
  }]
}

/** Redibuja la estructura completa (Plotly.react) -- al recibir
 * 'chain_full' (cambio de símbolo/DTE/strike-range), o al cambiar entre
 * NET GEX / CALL VS PUT (cambia la cantidad de trazas, no alcanza con
 * restyle). 'viewMode': 'net' | 'callput'. */
export function renderChainFull(el, payload, spot, viewMode = 'net') {
  const traces = buildTraces(payload, viewMode)

  if (initializedMode === null) {
    Plotly.newPlot(el, traces, baseLayout(spot, viewMode), { responsive: true, displaylogo: false })
  } else {
    Plotly.react(el, traces, baseLayout(spot, viewMode), { responsive: true, displaylogo: false })
  }
  initializedMode = viewMode
}

/** Actualización liviana (Plotly.restyle/relayout) en cada 'tick' -- nunca
 * newPlot/react acá salvo que el modo haya cambiado, es justo lo que
 * evita el parpadeo. */
export function updateTick(el, payload, spot, viewMode = 'net') {
  if (initializedMode === null || initializedMode !== viewMode) {
    renderChainFull(el, payload, spot, viewMode)
    return
  }

  if (viewMode === 'callput') {
    const strikes = payload.by_strike.map((s) => s.strike)
    const callGex = payload.by_strike.map((s) => s.call_gex)
    const putGex = payload.by_strike.map((s) => s.put_gex)
    const callOutline = strongestOutline(callGex)
    const putOutline = strongestOutline(putGex)
    Plotly.restyle(el, {
      x: [strikes, strikes], y: [callGex, putGex],
      'marker.line.color': [callOutline.colors, putOutline.colors],
      'marker.line.width': [callOutline.widths, putOutline.widths],
    })
  } else {
    const strikes = payload.by_strike.map((s) => s.strike)
    const netGex = payload.by_strike.map((s) => s.net_gex)
    const colors = netGex.map((v) => (v >= 0 ? COLOR_POSITIVE : COLOR_NEGATIVE))
    const outline = strongestOutline(netGex)
    Plotly.restyle(el, {
      x: [strikes], y: [netGex], 'marker.color': [colors],
      'marker.line.color': [outline.colors], 'marker.line.width': [outline.widths],
    })
  }
  Plotly.relayout(el, { shapes: spotLineShape(spot) })
}

export function resetGexInfoChart() {
  initializedMode = null
}
