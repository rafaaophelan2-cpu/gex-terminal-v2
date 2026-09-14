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
    // 'overlay' en vez de 'group': las barras de Calls y Puts van a todo
    // el ancho del strike, una arriba (calls, siempre >=0) y otra abajo
    // (puts, siempre <=0) -- una sola columna por strike, sin el hueco
    // horizontal que 'group' dejaba entre ambas.
    barmode: isCallPut ? 'overlay' : undefined,
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
  forceResize(el)
}

// Mismo bug/arreglo ya confirmado en vivo en LIVE GAMMA (ver
// liveGammaChart.js): Plotly.react() reusa el ancho ya cacheado del
// chart en vez de volver a medir el contenedor -- si el contenedor
// cambió de tamaño mientras esta pestaña estaba oculta (cambio de
// división del sidebar, split-view, etc.), el chart queda dibujado
// chiquito/en una esquina hasta el próximo resize real del navegador.
// requestAnimationFrame difiere la medición al siguiente frame, después
// de que el navegador ya pintó el layout real del contenedor recién
// visible (medir en el mismo tick daba 0 o un tamaño intermedio).
//
// IMPORTANTE -- por qué esto NO va en updateTick() (más abajo): este
// contenedor (.chart-container) no tiene una altura fija de CSS, solo
// min-height -- su alto real lo termina resolviendo el layout flex de
// .gex-info-charts-column. Llamar Plotly.Plots.resize() una vez está
// bien (mide el contenedor y ajusta), pero updateTick() corre en CADA
// tick de WebSocket (~1/seg) indefinidamente mientras la pestaña esté
// abierta -- llamarlo ahí también hacía que el chart creciera un poco
// en cada resize (el contenedor sin alto fijo + el propio SVG de Plotly
// recién resizeado se retroalimentaban, sumando unos px de más por
// ciclo) hasta quedar gigante después de un rato en pantalla (reportado
// en vivo). El resize real que hace falta (cambio de tamaño del
// contenedor por split-view/sidebar) ya lo cubre forceGexInfoRedraw()
// en main.js, que llama a renderChainFull() -- y ESA sí necesita este
// forceResize, porque corre solo ante un cambio de layout real, no en
// cada tick.
function forceResize(el) {
  requestAnimationFrame(() => {
    Plotly.Plots.resize(el)?.catch(() => {})
  })
}

/** Actualización liviana (Plotly.restyle/relayout) en cada 'tick' -- nunca
 * newPlot/react ni Plotly.Plots.resize() acá salvo que el modo haya
 * cambiado (eso sí redibuja desde cero vía renderChainFull), es justo
 * lo que evita el parpadeo Y el crecimiento acumulado del chart. */
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
