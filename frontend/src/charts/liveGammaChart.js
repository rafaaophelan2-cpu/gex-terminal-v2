import Plotly from 'plotly.js-dist-min'
import { COLOR_ACCENT, COLOR_BG, COLOR_NEGATIVE, COLOR_POSITIVE } from '../theme.js'
import { nyWallClockToPlotlyString } from '../utils/time.js'

/** LIVE GAMMA llega por REST (igual que NET DRIFT), cada render es un
 * redibujado completo -- no hay distinción react/restyle acá.
 * 'candles' (opcional): velas reales de 1 minuto de Schwab
 * ({time, open, high, low, close}[]) para superponer sobre el heatmap en
 * vez de una simple línea de spot -- Lightweight Charts no puede hacer
 * el heatmap (no tiene ese tipo de serie), así que las velas van acá
 * mismo, dentro de Plotly, junto al heatmap.
 * 'dateStr' (YYYY-MM-DD): necesaria para convertir los "HH:MM" (hora NY)
 * de ambas series a timestamps reales -- los snapshots (~cada 60s, con
 * huecos irregulares) y las velas de Schwab (cada 1 min exacto) tienen
 * grillas de tiempo DISTINTAS; mezclarlas en un eje de categorías de
 * texto hacía que Plotly tratara cada hora única de ambas series como
 * una columna más, dejando el heatmap con huecos dispersos y las velas
 * amontonadas. Con un eje de tiempo real cada trazo se ubica en su
 * posición real sin interferir con el otro. */
export function renderLiveGammaChart(el, heatmap, walls, candles, dateStr) {
  if (!heatmap.times || heatmap.times.length === 0) return

  // Preservar el zoom/pan actual entre refrescos periódicos (ver
  // LIVE_GAMMA_REFRESH_MS en main.js, ~cada 30s) -- sin esto, cada
  // Plotly.react volvía a autorange y el zoom que el usuario acababa de
  // aplicar se "reseteaba" solo a los pocos segundos. el.layout lo deja
  // Plotly ya pegado al elemento del DOM tras el primer render.
  const prevXRange = el.layout?.xaxis?.range
  const prevYRange = el.layout?.yaxis?.range

  const maxAbs = heatmap.z.reduce(
    (acc, row) => Math.max(acc, ...row.map((v) => Math.abs(v))),
    1,
  )

  const heatmapX = heatmap.times.map((t) => nyWallClockToPlotlyString(dateStr, t))

  const traces = [
    {
      type: 'heatmap',
      x: heatmapX,
      y: heatmap.strikes,
      z: heatmap.z,
      zmin: -maxAbs,
      zmax: maxAbs,
      // 'best' (bilineal) interpolaba entre bandas vecinas, mezclándolas
      // en un solo bloque continuo de color -- con zsmooth apagado, cada
      // banda queda con el ancho exacto que ya define el backend
      // (heatmap.py: BAND_HALF_WIDTH + perfil de suavizado explícito).
      zsmooth: false,
      colorscale: [
        [0.0, 'rgba(239, 68, 68, 0.55)'],
        [0.3, 'rgba(239, 68, 68, 0.10)'],
        [0.5, 'rgba(6, 8, 13, 0.0)'],
        [0.7, 'rgba(16, 185, 129, 0.10)'],
        [1.0, 'rgba(16, 185, 129, 0.55)'],
      ],
      hovertemplate: 'Hora: %{x|%H:%M}<br>Strike: $%{y}<br>Net GEX: %{z:,.0f}<extra></extra>',
      colorbar: { title: { text: 'Net GEX', side: 'top' }, x: -0.08 },
    },
  ]

  if (candles && candles.length > 0) {
    const candlesX = candles.map((c) => nyWallClockToPlotlyString(dateStr, c.time))
    traces.push({
      type: 'candlestick',
      name: 'Spot',
      x: candlesX,
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
      type: 'scatter', mode: 'lines', name: 'Spot', x: heatmapX, y: heatmap.spot,
      line: { color: COLOR_ACCENT, width: 2 },
    })
  }

  const shapes = []
  const annotations = []
  if (walls) {
    // Orden = "dominancia": CW1/PW1 es el nivel con mayor Net GEX neto
    // (calls contra puts ya netos, no el tamaño bruto de cada lado) --
    // eso es justo lo que ya calcula compute_call_put_walls en el
    // backend, así que el ranking de las etiquetas es el mismo que ya
    // se usa para las líneas: un nivel con mucho open interest en calls
    // Y en puts que casi se cancelan pesa menos que uno más chico pero
    // mayormente de un solo lado.
    const levels = [
      [walls.cw1, '#10B981', 'solid', 'CW1'], [walls.cw2, '#10B981', 'dash', 'CW2'], [walls.cw3, '#10B981', 'dot', 'CW3'],
      [walls.pw1, '#EF4444', 'solid', 'PW1'], [walls.pw2, '#EF4444', 'dash', 'PW2'], [walls.pw3, '#EF4444', 'dot', 'PW3'],
      [walls.zero_gamma, COLOR_ACCENT, 'dash', 'Gamma Flip'],
    ]
    levels.forEach(([y, color, dash, label]) => {
      if (y) {
        shapes.push({
          type: 'line', x0: 0, x1: 1, xref: 'paper', y0: y, y1: y,
          line: { color, width: 1, dash },
        })
        // Ancladas al viewport (xref: 'paper', no a un instante real) --
        // así quedan siempre visibles en el borde izquierdo sin importar
        // cuánto se haga pan/zoom sobre el eje de tiempo. El eje de
        // strike está a la derecha (side: 'right'), por eso el label va
        // a la izquierda en vez de competir con esos ticks.
        annotations.push({
          x: 0.01, xref: 'paper', xanchor: 'left',
          y, yref: 'y', yanchor: 'middle',
          text: `<b>${label}</b>`,
          showarrow: false,
          font: { color, size: 10, family: 'JetBrains Mono, monospace' },
          bgcolor: 'rgba(6, 8, 13, 0.75)',
          bordercolor: color,
          borderwidth: 1,
          borderpad: 2,
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
      type: 'date', tickformat: '%H:%M', rangeslider: { visible: false },
      ...(prevXRange ? { range: prevXRange, autorange: false } : {}),
    },
    yaxis: {
      title: 'Strike ($)', gridcolor: 'rgba(255,255,255,0.05)', side: 'right',
      ...(prevYRange ? { range: prevYRange, autorange: false } : {}),
    },
    shapes,
    annotations,
    hoverlabel: {
      font: { family: 'JetBrains Mono, monospace', size: 12, color: '#F0F6FC' },
      bgcolor: '#0E131F',
      bordercolor: 'rgba(255,255,255,0.15)',
    },
    showlegend: false,
    // 'pan' por defecto -- con 'zoom' (default de Plotly), el primer
    // click-y-arrastre del usuario recortaba/hacía zoom sin querer en
    // vez de simplemente mover la vista.
    dragmode: 'pan',
    margin: { l: 80, r: 60, t: 30, b: 50 },
    height: 650,
  }

  Plotly.react(el, traces, layout, { responsive: true, displaylogo: false, scrollZoom: true })
}
