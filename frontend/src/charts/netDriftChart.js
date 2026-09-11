import Plotly from 'plotly.js-dist-min'
import { COLOR_ACCENT, COLOR_BG, COLOR_NEGATIVE, COLOR_POSITIVE } from '../theme.js'

const COLOR_NET = '#F59E0B'

/** NET DRIFT no llega por tick (es REST, refrescado cada tanto) -- cada
 * render es un redibujado completo, no hace falta la distinción
 * react/restyle que sí importa en los paneles que reciben WS. */
export function renderNetDriftChart(el, series) {
  if (!series.time || series.time.length === 0) return

  const callsAbs = series.call_gex.map((v) => Math.abs(v))
  const putsAbs = series.put_gex.map((v) => Math.abs(v))

  const traces = [
    {
      type: 'scatter', mode: 'lines', name: 'Calls', x: series.time, y: callsAbs,
      line: { color: COLOR_POSITIVE, width: 2 },
    },
    {
      type: 'scatter', mode: 'lines', name: 'Puts', x: series.time, y: putsAbs,
      line: { color: COLOR_NEGATIVE, width: 2 },
    },
    {
      type: 'scatter', mode: 'lines', name: 'Net', x: series.time, y: series.net_gex,
      line: { color: COLOR_NET, width: 2 },
    },
    {
      type: 'scatter', mode: 'lines', name: 'Spot', x: series.time, y: series.spot, yaxis: 'y2',
      line: { color: COLOR_ACCENT, width: 2 },
    },
  ]

  const layout = {
    plot_bgcolor: COLOR_BG,
    paper_bgcolor: COLOR_BG,
    font: { color: '#D1D5DB', family: 'JetBrains Mono, monospace', size: 11 },
    xaxis: { title: 'Hora', gridcolor: 'rgba(255,255,255,0.05)' },
    yaxis: { title: 'GEX ($)', gridcolor: 'rgba(255,255,255,0.05)' },
    yaxis2: { title: 'Spot ($)', overlaying: 'y', side: 'right', showgrid: false },
    hoverlabel: {
      font: { family: 'JetBrains Mono, monospace', size: 12, color: '#F0F6FC' },
      bgcolor: '#0E131F',
      bordercolor: 'rgba(255,255,255,0.15)',
    },
    legend: { orientation: 'h', y: 1.08, font: { color: '#D1D5DB' } },
    margin: { l: 70, r: 60, t: 30, b: 50 },
    height: 600,
    hovermode: 'x unified',
  }

  Plotly.react(el, traces, layout, { responsive: true, displaylogo: false })
}
