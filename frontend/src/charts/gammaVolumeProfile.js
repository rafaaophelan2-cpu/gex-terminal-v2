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
// Strikes ordenados tal cual quedaron dibujados en el eje Y (categórico,
// de menor a mayor) -- setGammaVolumeProfileVisibleRange() los necesita
// para poder traducir "estos strikes están visibles" a un ÍNDICE dentro
// de la lista de categorías, que es lo que Plotly realmente entiende
// como rango en un eje de tipo category (ver comentario ahí abajo).
let lastRenderedStrikes = []

export function renderGammaVolumeProfile(el, grid) {
  if (!grid.strikes || grid.strikes.length === 0) {
    el.innerHTML = ''
    lastRenderedStrikes = []
    return
  }

  const rows = grid.strikes
    .map((strike, idx) => ({ strike, total: grid.values[idx].reduce((a, b) => a + b, 0) }))
    .sort((a, b) => a.strike - b.strike)

  lastRenderedStrikes = rows.map((r) => r.strike)
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

/** Sincroniza el rango visible del eje Y (strikes) con lo que el usuario
 * está viendo en ese momento en la tabla de Gamma Heatmap -- sin esto, el
 * profile mostraba SIEMPRE los ~50-100 strikes completos apretados en un
 * solo panel (ilegible, "muy zoomeado afuera"); ahora se "recorta" al
 * mismo rango que main.js calcula a partir del scroll de la tabla, así
 * ambos se mueven juntos.
 *
 * Un eje 'category' de Plotly NO acepta un [min, max] de labels/strings
 * como rango (probado en vivo: lo dejaba completamente en blanco, sin
 * barras ni ticks) -- internamente cada categoría vive en una posición
 * ORDINAL (0, 1, 2...), y el rango tiene que expresarse en esos índices.
 * Por eso lastRenderedStrikes existe: para poder traducir "quiero ver
 * desde el strike X hasta el Y" a "desde el índice N hasta el M" antes
 * de llamar a relayout. */
export function setGammaVolumeProfileVisibleRange(el, minStrike, maxStrike) {
  if (minStrike == null || maxStrike == null || lastRenderedStrikes.length === 0) return

  const minIdx = lastRenderedStrikes.findIndex((s) => s >= minStrike)
  let maxIdx = -1
  for (let i = lastRenderedStrikes.length - 1; i >= 0; i--) {
    if (lastRenderedStrikes[i] <= maxStrike) {
      maxIdx = i
      break
    }
  }
  if (minIdx === -1 || maxIdx === -1 || minIdx > maxIdx) return

  Plotly.relayout(el, {
    'yaxis.autorange': false,
    // -0.5/+0.5: cada categoría ocupa el rango [i-0.5, i+0.5] en el eje
    // ordinal -- sin este margen, las barras de los strikes en los
    // bordes del rango elegido quedarían cortadas a la mitad.
    'yaxis.range': [minIdx - 0.5, maxIdx + 0.5],
  })
}
