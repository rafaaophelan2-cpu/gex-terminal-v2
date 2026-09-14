import Plotly from 'plotly.js-dist-min'
import { COLOR_BG } from '../theme.js'

const SCENE_AXIS = {
  gridcolor: 'rgba(255,255,255,0.1)',
  backgroundcolor: COLOR_BG,
  color: '#D1D5DB',
}

/** 3D SURFACE: malla Net GEX real sobre strike (Y) x DTE (X), mismos
 * datos que el GRID (ver domain/gamma_grid.py) pero como superficie en
 * vez de tabla -- deja ver de un vistazo dónde se concentra el gamma a
 * través de expiraciones, no solo dentro de una. Verde/rojo igual que el
 * resto de la app (positivo/negativo), centrado en 0 con cmid para que
 * el punto neutro del degradado caiga siempre en Net GEX = 0 sin
 * importar si el lado positivo o negativo domina el rango. */
export function renderGammaSurfaceChart(el, grid) {
  if (!grid.strikes || grid.strikes.length === 0) {
    el.innerHTML = ''
    return
  }

  const dtes = grid.columns.map((c) => c.dte)
  const maxAbs = grid.values.reduce(
    (acc, row) => Math.max(acc, ...row.map((v) => Math.abs(v ?? 0))),
    1,
  )

  const trace = {
    type: 'surface',
    x: dtes,
    y: grid.strikes,
    z: grid.values,
    colorscale: [
      [0.0, 'rgb(239, 68, 68)'],
      [0.5, 'rgb(30, 34, 45)'],
      [1.0, 'rgb(16, 185, 129)'],
    ],
    cmin: -maxAbs,
    cmax: maxAbs,
    cmid: 0,
    colorbar: { title: { text: 'Net GEX', side: 'top' }, tickfont: { size: 9 } },
    hovertemplate: 'DTE: %{x}<br>Strike: $%{y}<br>Net GEX: %{z:,.0f}<extra></extra>',
  }

  const layout = {
    paper_bgcolor: COLOR_BG,
    font: { color: '#D1D5DB', family: 'JetBrains Mono, monospace', size: 11 },
    scene: {
      xaxis: { ...SCENE_AXIS, title: 'DTE' },
      yaxis: { ...SCENE_AXIS, title: 'Strike ($)' },
      zaxis: { ...SCENE_AXIS, title: 'Net GEX' },
      camera: { eye: { x: 1.6, y: -1.6, z: 0.8 } },
    },
    margin: { l: 0, r: 0, t: 20, b: 0 },
    height: 650,
  }

  Plotly.react(el, [trace], layout, { responsive: true, displaylogo: false })
  forceResize(el)
}

// Mismo bug/arreglo ya confirmado en vivo en LIVE GAMMA/GEX INFO: esta
// pestaña vive oculta (display:none) hasta que el usuario entra a Chain
// Analytics, así que Plotly mide el contenedor en 0/ancho viejo la
// primera vez -- Plotly.Plots.resize(el) en el próximo frame (después de
// que el navegador ya pintó el layout real del contenedor recién
// visible) lo corrige.
function forceResize(el) {
  requestAnimationFrame(() => {
    Plotly.Plots.resize(el)?.catch(() => {})
  })
}
