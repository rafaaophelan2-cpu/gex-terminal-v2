import Plotly from 'plotly.js-dist-min'
import { COLOR_ACCENT, COLOR_BG, COLOR_NEGATIVE, COLOR_POSITIVE } from '../theme.js'

/** LIVE GAMMA llega por REST (igual que NET DRIFT), cada render es un
 * redibujado completo -- no hay distinción react/restyle acá.
 * 'candles' (opcional): velas reales de 1 minuto de Schwab
 * ({time, open, high, low, close}[]) para superponer sobre el heatmap en
 * vez de una simple línea de spot -- Lightweight Charts no puede hacer
 * el heatmap (no tiene ese tipo de serie), así que las velas van acá
 * mismo, dentro de Plotly, junto al heatmap. */
export function renderLiveGammaChart(el, heatmap, walls, candles) {
  if (!heatmap.times || heatmap.times.length === 0) return

  const maxAbs = heatmap.z.reduce(
    (acc, row) => Math.max(acc, ...row.map((v) => Math.abs(v))),
    1,
  )

  const traces = [
    {
      type: 'heatmap',
      x: heatmap.times,
      y: heatmap.strikes,
      z: heatmap.z,
      zmin: -maxAbs,
      zmax: maxAbs,
      zsmooth: 'best',
      colorscale: [
        [0.0, 'rgba(239, 68, 68, 0.55)'],
        [0.3, 'rgba(239, 68, 68, 0.10)'],
        [0.5, 'rgba(6, 8, 13, 0.0)'],
        [0.7, 'rgba(16, 185, 129, 0.10)'],
        [1.0, 'rgba(16, 185, 129, 0.55)'],
      ],
      hovertemplate: 'Hora: %{x}<br>Strike: $%{y}<br>Net GEX: %{z:,.0f}<extra></extra>',
      colorbar: { title: { text: 'Net GEX', side: 'top' }, x: -0.08 },
    },
  ]

  if (candles && candles.length > 0) {
    traces.push({
      type: 'candlestick',
      name: 'Spot',
      x: candles.map((c) => c.time),
      open: candles.map((c) => c.open),
      high: candles.map((c) => c.high),
      low: candles.map((c) => c.low),
      close: candles.map((c) => c.close),
      increasing: { line: { color: COLOR_POSITIVE }, fillcolor: COLOR_POSITIVE },
      decreasing: { line: { color: COLOR_NEGATIVE }, fillcolor: COLOR_NEGATIVE },
    })
  } else {
    // Fallback: sin velas de Schwab disponibles, al menos la línea de
    // spot que ya viene en los snapshots guardados.
    traces.push({
      type: 'scatter', mode: 'lines', name: 'Spot', x: heatmap.times, y: heatmap.spot,
      line: { color: COLOR_ACCENT, width: 2 },
    })
  }

  const shapes = []
  if (walls) {
    const levels = [
      [walls.cw1, '#10B981', 'solid'], [walls.cw2, '#10B981', 'dash'], [walls.cw3, '#10B981', 'dot'],
      [walls.pw1, '#EF4444', 'solid'], [walls.pw2, '#EF4444', 'dash'], [walls.pw3, '#EF4444', 'dot'],
    ]
    levels.forEach(([y, color, dash]) => {
      if (y) {
        shapes.push({
          type: 'line', x0: 0, x1: 1, xref: 'paper', y0: y, y1: y,
          line: { color, width: 1, dash },
        })
      }
    })
  }

  const layout = {
    plot_bgcolor: COLOR_BG,
    paper_bgcolor: COLOR_BG,
    font: { color: '#D1D5DB', family: 'JetBrains Mono, monospace', size: 11 },
    xaxis: {
      title: 'Hora', gridcolor: 'rgba(255,255,255,0.05)',
      type: 'category', categoryorder: 'category ascending', rangeslider: { visible: false },
    },
    yaxis: { title: 'Strike ($)', gridcolor: 'rgba(255,255,255,0.05)', side: 'right' },
    shapes,
    hoverlabel: {
      font: { family: 'JetBrains Mono, monospace', size: 12, color: '#F0F6FC' },
      bgcolor: '#0E131F',
      bordercolor: 'rgba(255,255,255,0.15)',
    },
    showlegend: false,
    margin: { l: 80, r: 60, t: 30, b: 50 },
    height: 650,
  }

  Plotly.react(el, traces, layout, { responsive: true, displaylogo: false })
}
