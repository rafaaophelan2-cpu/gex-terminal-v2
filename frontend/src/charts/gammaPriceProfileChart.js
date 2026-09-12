import Plotly from 'plotly.js-dist-min'
import { COLOR_BG, COLOR_NEGATIVE, COLOR_POSITIVE } from '../theme.js'

/** "Gamma Price Profile": curva de Net Gamma proyectado en precios
 * hipotéticos alrededor del spot (ver domain/gamma_price_profile.py).
 * Verde por encima de 0 / rojo por debajo, como una sola curva continua
 * -- Plotly no soporta un color de relleno condicional en una sola
 * traza, así que se arma con DOS trazas superpuestas sobre el mismo eje:
 * una con el negativo puro (fill tozeroy rojo) y otra con el positivo
 * puro (fill tozeroy verde). Juntas se ven como una sola curva que
 * cambia de color en el cruce por cero. */
export function renderGammaPriceProfileChart(el, priceProfile) {
  if (!priceProfile || !priceProfile.prices || priceProfile.prices.length === 0) {
    el.innerHTML = ''
    return
  }

  const { prices, net_gamma: netGamma } = priceProfile
  const negativePart = netGamma.map((v) => (v < 0 ? v : 0))
  const positivePart = netGamma.map((v) => (v > 0 ? v : 0))

  const commonTrace = {
    type: 'scatter', mode: 'lines', x: prices,
    line: { shape: 'spline', smoothing: 0.6, width: 2 },
    hoverinfo: 'skip',
  }

  const traces = [
    {
      ...commonTrace, y: negativePart, name: 'Negativo',
      line: { ...commonTrace.line, color: COLOR_NEGATIVE },
      fill: 'tozeroy', fillcolor: 'rgba(239, 68, 68, 0.25)',
    },
    {
      ...commonTrace, y: positivePart, name: 'Positivo',
      line: { ...commonTrace.line, color: COLOR_POSITIVE },
      fill: 'tozeroy', fillcolor: 'rgba(16, 185, 129, 0.25)',
    },
    // Traza invisible con el valor REAL (sin partir en positivo/negativo)
    // solo para un hover legible con el número completo en cada precio.
    {
      type: 'scatter', mode: 'lines', x: prices, y: netGamma,
      line: { color: 'rgba(0,0,0,0)', width: 0 },
      hovertemplate: 'Precio: $%{x:,.2f}<br>Net Gamma: %{y:,.0f}<extra></extra>',
    },
  ]

  const layout = {
    plot_bgcolor: COLOR_BG,
    paper_bgcolor: COLOR_BG,
    font: { color: '#D1D5DB', family: 'JetBrains Mono, monospace', size: 11 },
    xaxis: { title: 'Precio ($)', gridcolor: 'rgba(255,255,255,0.05)', zeroline: false },
    yaxis: {
      title: 'Net Gamma ($)', gridcolor: 'rgba(255,255,255,0.05)',
      zeroline: true, zerolinecolor: 'rgba(255,255,255,0.2)', zerolinewidth: 1,
    },
    showlegend: false,
    hoverlabel: {
      font: { family: 'JetBrains Mono, monospace', size: 12, color: '#F0F6FC' },
      bgcolor: '#0E131F',
      bordercolor: 'rgba(255,255,255,0.15)',
    },
    margin: { l: 70, r: 30, t: 20, b: 50 },
    height: 380,
  }

  Plotly.react(el, traces, layout, { responsive: true, displaylogo: false })
}
