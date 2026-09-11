import Plotly from 'plotly.js-dist-min'
import { COLOR_ACCENT, COLOR_BG, COLOR_NEGATIVE, COLOR_POSITIVE } from '../theme.js'

const HOVER = {
  font: { family: 'JetBrains Mono, monospace', size: 12, color: '#F0F6FC' },
  bgcolor: '#0E131F',
  bordercolor: 'rgba(255,255,255,0.15)',
}

export function renderBackgammaSpotChart(el, heatmap, currentIndex) {
  if (!heatmap.times || heatmap.times.length === 0) return

  const traces = [
    {
      type: 'scatter', mode: 'lines', name: 'Spot', x: heatmap.times, y: heatmap.spot,
      line: { color: COLOR_ACCENT, width: 2 },
    },
    {
      type: 'scatter', mode: 'markers', name: 'Ahora', showlegend: false,
      x: [heatmap.times[currentIndex]], y: [heatmap.spot[currentIndex]],
      marker: { color: '#FBBF24', size: 12, line: { color: '#fff', width: 1.5 } },
    },
  ]

  const layout = {
    plot_bgcolor: COLOR_BG,
    paper_bgcolor: COLOR_BG,
    font: { color: '#D1D5DB', family: 'JetBrains Mono, monospace', size: 11 },
    xaxis: { gridcolor: 'rgba(255,255,255,0.05)' },
    yaxis: { title: 'Spot ($)', gridcolor: 'rgba(255,255,255,0.05)' },
    hoverlabel: HOVER,
    showlegend: false,
    margin: { l: 70, r: 30, t: 20, b: 40 },
    height: 260,
  }

  Plotly.react(el, traces, layout, { responsive: true, displaylogo: false })
}

export function renderBackgammaStrikeChart(el, heatmap, currentIndex) {
  if (!heatmap.strikes || heatmap.strikes.length === 0) return

  const values = heatmap.z.map((row) => row[currentIndex])
  const colors = values.map((v) => (v >= 0 ? COLOR_POSITIVE : COLOR_NEGATIVE))
  const spot = heatmap.spot[currentIndex]

  const trace = {
    type: 'bar', x: heatmap.strikes, y: values, marker: { color: colors },
    hovertemplate: 'Strike: $%{x}<br>Net GEX: %{y:,.0f}<extra></extra>',
  }

  const shapes = spot
    ? [{ type: 'line', x0: spot, x1: spot, y0: 0, y1: 1, yref: 'paper', line: { color: COLOR_ACCENT, width: 1.5, dash: 'dash' } }]
    : []

  const layout = {
    plot_bgcolor: COLOR_BG,
    paper_bgcolor: COLOR_BG,
    font: { color: '#D1D5DB', family: 'JetBrains Mono, monospace', size: 11 },
    title: { text: 'Strike Profile (Net GEX) en el instante seleccionado', font: { color: '#F0F6FC', size: 14 } },
    xaxis: { title: 'Strike ($)', gridcolor: 'rgba(255,255,255,0.05)' },
    yaxis: { title: 'Net GEX ($)', gridcolor: 'rgba(255,255,255,0.05)', zeroline: true, zerolinecolor: 'rgba(255,255,255,0.15)' },
    shapes,
    hoverlabel: HOVER,
    showlegend: false,
    margin: { l: 70, r: 30, t: 50, b: 50 },
    height: 420,
  }

  Plotly.react(el, [trace], layout, { responsive: true, displaylogo: false })
}
