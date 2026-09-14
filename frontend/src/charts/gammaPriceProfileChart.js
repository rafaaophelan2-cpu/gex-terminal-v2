import Plotly from 'plotly.js-dist-min'
import { COLOR_BG, COLOR_NEGATIVE, COLOR_POSITIVE } from '../theme.js'

// A diferencia de gexInfoChart.js (que ya separaba redraw completo de
// update liviano), esta acá SIEMPRE hacía Plotly.react() -- incluyendo
// en cada tick normal de WebSocket (~1/seg, ver main.js). Plotly.react()
// vuelve a pasar por el pipeline de autosize cuando responsive:true está
// activo y el contenedor no tiene una altura de CSS fija (acá solo tiene
// min-height, el alto real lo resuelve el layout flex) -- llamado sin
// parar durante minutos, eso fue justo lo que hizo que el chart creciera
// solo con el tiempo (reportado en vivo, mismo mecanismo que se encontró
// y arregló en gexInfoChart.js). Se separa igual que ahí: react() completo
// solo para el primer render o un redraw real (cambio de símbolo/layout,
// ver forceGexInfoRedraw en main.js), y restyle liviano (sin tocar
// tamaño) para el resto de los ticks.
let priceProfileInitialized = false

function buildPriceProfileTraces(priceProfile) {
  const { prices, net_gamma: netGamma } = priceProfile
  const negativePart = netGamma.map((v) => (v < 0 ? v : 0))
  const positivePart = netGamma.map((v) => (v > 0 ? v : 0))
  return { prices, netGamma, negativePart, positivePart }
}

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
    priceProfileInitialized = false
    return
  }

  const { prices, netGamma, negativePart, positivePart } = buildPriceProfileTraces(priceProfile)

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
    // Mismo alto que el gráfico de Net GEX Profile (gexInfoChart.js) --
    // antes era más bajo (380) y dejaba un hueco vacío grande en el
    // contenedor de abajo.
    height: 600,
  }

  Plotly.react(el, traces, layout, { responsive: true, displaylogo: false })
  priceProfileInitialized = true
}

/** Actualización liviana (Plotly.restyle, sin tocar layout/tamaño) para
 * los ticks normales de WebSocket -- ver comentario grande más arriba.
 * Si todavía no hubo un render completo (primera carga, o el chart se
 * vació por falta de datos) cae a renderGammaPriceProfileChart(). */
export function updateGammaPriceProfileTick(el, priceProfile) {
  if (!priceProfile || !priceProfile.prices || priceProfile.prices.length === 0) {
    el.innerHTML = ''
    priceProfileInitialized = false
    return
  }
  if (!priceProfileInitialized) {
    renderGammaPriceProfileChart(el, priceProfile)
    return
  }

  const { prices, netGamma, negativePart, positivePart } = buildPriceProfileTraces(priceProfile)
  Plotly.restyle(el, { x: [prices, prices, prices], y: [negativePart, positivePart, netGamma] })
}

/** Mismo criterio que resetGexInfoChart() -- se llama al cambiar de
 * símbolo o volver a loguear, para que el próximo dato entrante haga un
 * render completo (react, con su layout/tamaño real) en vez de un
 * restyle liviano sobre un chart que quedó de un símbolo anterior. */
export function resetGammaPriceProfileChart() {
  priceProfileInitialized = false
}
