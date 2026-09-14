import Plotly from 'plotly.js-dist-min'
import { COLOR_BG } from '../theme.js'

const SCENE_AXIS = {
  gridcolor: 'rgba(255,255,255,0.1)',
  backgroundcolor: COLOR_BG,
  color: '#D1D5DB',
}

/** 3D VOL SURFACE: malla de IV% (convención OTM, ver domain/vol_surface.py)
 * sobre strike (Y) x DTE (X) -- a diferencia de Net GEX, la IV no tiene
 * signo, así que usa un colorscale secuencial (no verde/rojo divergente)
 * en vez de estar centrado en 0. Los huecos en la malla (celdas 'null',
 * strike sin cotización en esa expiración) los deja como gaps Plotly.js
 * de forma nativa, sin necesitar 'connectgaps'. */
export function renderVolSurfaceChart(el, grid) {
  if (!grid.strikes || grid.strikes.length === 0) {
    el.innerHTML = ''
    return
  }

  const dtes = grid.columns.map((c) => c.dte)

  const trace = {
    type: 'surface',
    x: dtes,
    y: grid.strikes,
    z: grid.values,
    colorscale: 'Viridis',
    colorbar: { title: { text: 'IV %', side: 'top' }, tickfont: { size: 9 } },
    hovertemplate: 'DTE: %{x}<br>Strike: $%{y}<br>IV: %{z:.1f}%<extra></extra>',
  }

  const layout = {
    paper_bgcolor: COLOR_BG,
    font: { color: '#D1D5DB', family: 'JetBrains Mono, monospace', size: 11 },
    scene: {
      xaxis: { ...SCENE_AXIS, title: 'DTE' },
      yaxis: { ...SCENE_AXIS, title: 'Strike ($)' },
      zaxis: { ...SCENE_AXIS, title: 'IV %' },
      camera: { eye: { x: 1.6, y: -1.6, z: 0.8 } },
    },
    margin: { l: 0, r: 0, t: 20, b: 0 },
    height: 650,
  }

  Plotly.react(el, [trace], layout, { responsive: true, displaylogo: false })
  forceResize(el)
}

// Mismo bug/arreglo ya confirmado en vivo en LIVE GAMMA/GEX INFO -- ver
// el comentario en gammaSurfaceChart.js::forceResize.
function forceResize(el) {
  requestAnimationFrame(() => {
    Plotly.Plots.resize(el)?.catch(() => {})
  })
}
