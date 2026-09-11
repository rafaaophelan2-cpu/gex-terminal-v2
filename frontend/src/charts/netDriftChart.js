import { createChart, LineSeries } from 'lightweight-charts'
import { COLOR_ACCENT, COLOR_BG, COLOR_NEGATIVE, COLOR_POSITIVE } from '../theme.js'

const COLOR_NET = '#F59E0B'

function abbreviateGex(value) {
  const abs = Math.abs(value)
  const sign = value < 0 ? '-' : ''
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K`
  return `${sign}${abs.toFixed(0)}`
}

const GEX_PRICE_FORMAT = { type: 'custom', formatter: abbreviateGex, minMove: 1 }

let chart = null
let callsSeries = null
let putsSeries = null
let netSeries = null
let spotSeries = null
let resizeObserver = null

/** Convierte una fecha+hora en hora de Nueva York (STORAGE_TZ del
 * backend) a segundos UTC -- Lightweight Charts necesita timestamps
 * reales para el eje de tiempo, no strings "HH:MM" sueltos. Usa el
 * truco estándar de comparar cómo el mismo instante se imprime en NY vs
 * UTC para derivar el offset (maneja EDT/EST solo con Intl, sin
 * librería de fechas). */
function nyWallClockToUtcSeconds(dateStr, timeStr) {
  const naive = new Date(`${dateStr}T${timeStr}:00`)
  const nyString = naive.toLocaleString('en-US', { timeZone: 'America/New_York' })
  const utcString = naive.toLocaleString('en-US', { timeZone: 'UTC' })
  const offsetMs = new Date(utcString).getTime() - new Date(nyString).getTime()
  return Math.floor((naive.getTime() + offsetMs) / 1000)
}

function ensureChart(el) {
  if (chart) return

  chart = createChart(el, {
    height: 600,
    layout: {
      background: { color: COLOR_BG },
      textColor: '#D1D5DB',
      fontFamily: 'JetBrains Mono, monospace',
    },
    grid: {
      vertLines: { color: 'rgba(255,255,255,0.05)' },
      horzLines: { color: 'rgba(255,255,255,0.05)' },
    },
    timeScale: { timeVisible: true, secondsVisible: false, borderColor: 'rgba(255,255,255,0.1)' },
    rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
    leftPriceScale: { visible: true, borderColor: 'rgba(255,255,255,0.1)' },
    crosshair: { mode: 0 },
  })

  // priceLineVisible/lastValueVisible en false: por defecto cada serie
  // dibuja una línea punteada horizontal en su último valor -- con 4
  // series eso son 4 líneas flotando sin relación con el resto de la
  // curva, que es justo lo que se veía como "desincronizado".
  const commonOpts = { lineWidth: 2, priceLineVisible: false, lastValueVisible: false }

  callsSeries = chart.addSeries(LineSeries, { ...commonOpts, color: COLOR_POSITIVE, title: 'Calls', priceFormat: GEX_PRICE_FORMAT })
  putsSeries = chart.addSeries(LineSeries, { ...commonOpts, color: COLOR_NEGATIVE, title: 'Puts', priceFormat: GEX_PRICE_FORMAT })
  netSeries = chart.addSeries(LineSeries, { ...commonOpts, color: COLOR_NET, title: 'Net', priceFormat: GEX_PRICE_FORMAT })
  spotSeries = chart.addSeries(LineSeries, {
    ...commonOpts, color: COLOR_ACCENT, title: 'Spot', priceScaleId: 'left',
  })

  resizeObserver = new ResizeObserver((entries) => {
    const { width, height } = entries[0].contentRect
    if (width > 0 && height > 0) chart.resize(width, height)
  })
  resizeObserver.observe(el)
}

/** dateStr: la fecha (YYYY-MM-DD) seleccionada en el picker -- necesaria
 * para convertir los "HH:MM" de la serie a timestamps reales. */
export function renderNetDriftChart(el, series, dateStr) {
  if (!series.time || series.time.length === 0) return
  ensureChart(el)

  const times = series.time.map((t) => nyWallClockToUtcSeconds(dateStr, t))

  callsSeries.setData(times.map((time, i) => ({ time, value: Math.abs(series.call_gex[i]) })))
  putsSeries.setData(times.map((time, i) => ({ time, value: Math.abs(series.put_gex[i]) })))
  netSeries.setData(times.map((time, i) => ({ time, value: series.net_gex[i] })))
  spotSeries.setData(times.map((time, i) => ({ time, value: series.spot[i] })))

  chart.timeScale().fitContent()
}
