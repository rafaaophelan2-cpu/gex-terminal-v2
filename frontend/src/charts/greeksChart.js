import Plotly from 'plotly.js-dist-min'
import { COLOR_BG, COLOR_NEGATIVE, COLOR_POSITIVE } from '../theme.js'
import { strongestOutline } from '../utils/chartHighlight.js'

const GREEK_FIELD = { dex: 'net_dex', tex: 'net_tex', vex: 'net_vex', chex: 'net_chex', vanna: 'net_vanna' }
const GREEK_TITLE = {
  dex: 'Net Delta Exposure (DEX) por Strike',
  tex: 'Net Theta Exposure (TEX) por Strike',
  vex: 'Net Vega Exposure (VEX) por Strike',
  chex: 'Net Charm Exposure (CHEX) por Strike',
  vanna: 'Net Vanna Exposure por Strike',
}

// Como con gexInfoChart: una sola instancia en pantalla para este MVP.
let initializedGreek = null

function baseLayout(title) {
  return {
    plot_bgcolor: COLOR_BG,
    paper_bgcolor: COLOR_BG,
    font: { color: '#D1D5DB', family: 'JetBrains Mono, monospace', size: 11 },
    title: { text: title, font: { color: '#F0F6FC', size: 15 } },
    xaxis: { title: 'Strike ($)', gridcolor: 'rgba(255,255,255,0.05)' },
    yaxis: { gridcolor: 'rgba(255,255,255,0.05)', zeroline: true, zerolinecolor: 'rgba(255,255,255,0.15)' },
    hoverlabel: {
      font: { family: 'JetBrains Mono, monospace', size: 12, color: '#F0F6FC' },
      bgcolor: '#0E131F',
      bordercolor: 'rgba(255,255,255,0.15)',
    },
    margin: { l: 70, r: 30, t: 50, b: 50 },
    height: 560,
    showlegend: false,
  }
}

/** greekKey: 'dex' | 'tex' | 'vex' | 'chex' | 'vanna'.
 * forceRedraw=true en cambios estructurales (cambiar de sub-tab, o hacerse
 * visible tras estar oculta) -- usa Plotly.react. Si no, restyle liviano
 * en cada tick, igual criterio que gexInfoChart. */
export function renderGreeksChart(el, greekKey, payload, forceRedraw = false) {
  if (!payload.by_strike || payload.by_strike.length === 0) return

  const field = GREEK_FIELD[greekKey]
  const strikes = payload.by_strike.map((s) => s.strike)
  const values = payload.by_strike.map((s) => s[field])
  const colors = values.map((v) => (v >= 0 ? COLOR_POSITIVE : COLOR_NEGATIVE))
  const outline = strongestOutline(values)
  const trace = {
    type: 'bar', x: strikes, y: values, marker: { color: colors, line: { color: outline.colors, width: outline.widths } },
    hovertemplate: 'Strike: $%{x}<br>Valor: %{y:,.2f}<extra></extra>',
  }

  if (forceRedraw || initializedGreek !== greekKey) {
    Plotly.react(el, [trace], baseLayout(GREEK_TITLE[greekKey]), { responsive: true, displaylogo: false })
    initializedGreek = greekKey
  } else {
    Plotly.restyle(el, {
      x: [strikes], y: [values], 'marker.color': [colors],
      'marker.line.color': [outline.colors], 'marker.line.width': [outline.widths],
    })
  }
}

export function resetGreeksChart() {
  initializedGreek = null
}
