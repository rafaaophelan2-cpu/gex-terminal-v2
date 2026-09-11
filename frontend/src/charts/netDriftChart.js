import { BaselineSeries, createChart, LineSeries } from 'lightweight-charts'
import { COLOR_ACCENT, COLOR_BG, COLOR_NEGATIVE, COLOR_POSITIVE } from '../theme.js'
import { nyWallClockToUtcSeconds } from '../utils/time.js'

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
let netWaveSeries = null
let resizeObserver = null
let lastRightDataRange = null

// Spot ($700ish) y Calls/Puts/Net (millones de GEX) vivían en DOS
// priceScale independientes ('left'/'right') para que ambos fueran
// visibles pese a la diferencia de magnitud -- pero eso significaba dos
// ejes que Lightweight Charts arrastra/zoomea cada uno por su cuenta, y
// varios intentos de sincronizarlos a mano (interceptar mousedown/
// mousemove, reimplementar drag y wheel, leer/escribir rangos "frescos")
// terminaron siendo frágiles: alguno de los dos ejes quedaba pegado según
// el orden exacto en que la librería procesaba los eventos, algo que no
// se puede depurar sin poder correr esto en un navegador real.
//
// En vez de seguir peleando esa sincronización, se elimina la necesidad
// de sincronizar nada: Spot pasa a vivir en la MISMA escala 'right' que
// Calls/Puts/Net, reescalado matemáticamente para caber en un rango
// comparable (ver computeSpotTransform). Con una sola escala, cualquier
// zoom o arrastre -- nativo de la librería, sin código propio -- mueve
// las 4 líneas a la vez por construcción, no porque algo las sincronice.
// El precio real de Spot se sigue mostrando bien en el tooltip/etiqueta
// gracias a priceFormat (ver formatSpotValue), que deshace la
// transformación al mostrar el número.
let spotTransform = null

function computeSpotTransform(spotValues, rightRange) {
  if (!spotValues || spotValues.length === 0 || !rightRange) return null
  const spotMin = Math.min(...spotValues)
  const spotMax = Math.max(...spotValues)
  const spotSpan = (spotMax - spotMin) || Math.abs(spotMax) || 1
  const rightSpan = (rightRange.to - rightRange.from) || 1

  // Spot se reescala al MISMO rango completo que Calls/Puts/Net (no a
  // una banda propia más abajo, como una primera versión de esto hacía)
  // -- una referencia real de "Net Drift" (gráfico de Premium, con
  // Calls/Puts/subyacente) muestra las tres líneas entrelazadas en el
  // mismo espacio visual, cruzándose entre sí con normalidad; separarlas
  // en bandas horizontales distintas (lo que hacía la versión anterior)
  // es lo que se veía "raro" -- cada línea igual de lejos e indiferente
  // de las demás en vez de reaccionar junto al resto del mercado.
  const scale = rightSpan / spotSpan
  const offset = rightRange.from - spotMin * scale
  return { scale, offset }
}

function toChartValue(spot, transform) {
  return spot * transform.scale + transform.offset
}

function fromChartValue(chartValue, transform) {
  return (chartValue - transform.offset) / transform.scale
}

function formatSpotValue(chartValue) {
  if (!spotTransform) return chartValue.toFixed(2)
  return `$${fromChartValue(chartValue, spotTransform).toFixed(2)}`
}

const SPOT_PRICE_FORMAT = { type: 'custom', formatter: formatSpotValue, minMove: 0.0001 }

function rangeFromValues(values, paddingFraction = 0.1) {
  if (!values || values.length === 0) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const pad = (max - min) * paddingFraction || Math.abs(max) * paddingFraction || 1
  return { from: min - pad, to: max + pad }
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
    timeScale: {
      timeVisible: true, secondsVisible: false, borderColor: 'rgba(255,255,255,0.1)',
      // Deja un margen en blanco a la derecha del último dato -- sin
      // esto, fitContent() (llamado en cada refresh) pegaba el punto
      // más reciente justo contra el eje de precio, y con el zoom por
      // defecto el usuario tenía que arrastrar para ver dónde está
      // "ahora" en vez de verlo de entrada.
      rightOffset: 8,
    },
    // scaleMargins deja el 22% inferior del panel libre para la "ola" de
    // Net GEX (netWaveSeries, ver abajo) -- sin este margen, Calls/Puts/
    // Net/Spot ocupan todo el alto y la ola quedaría tapada debajo de
    // ellas en vez de en su propio espacio.
    rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)', scaleMargins: { top: 0.05, bottom: 0.25 } },
    crosshair: { mode: 0 },
    // Con Spot ya viviendo en la escala 'right' (ver comentario grande
    // arriba), el drag-to-zoom y el doble-click-reset NATIVOS de la
    // librería alcanzan y sobran -- ya no hace falta reimplementarlos a
    // mano, porque no hay un segundo eje que se pueda desincronizar.
    handleScale: {
      axisPressedMouseMove: { time: true, price: true },
      axisDoubleClickReset: { time: true, price: true },
      mouseWheel: true,
      pinch: true,
    },
  })

  // priceLineVisible/lastValueVisible en false: por defecto cada serie
  // dibuja una línea punteada horizontal en su último valor -- con 4
  // series eso son 4 líneas flotando sin relación con el resto de la
  // curva.
  const commonOpts = { lineWidth: 2, priceLineVisible: false, lastValueVisible: false }

  callsSeries = chart.addSeries(LineSeries, { ...commonOpts, color: COLOR_POSITIVE, title: 'Calls', priceFormat: GEX_PRICE_FORMAT })
  putsSeries = chart.addSeries(LineSeries, { ...commonOpts, color: COLOR_NEGATIVE, title: 'Puts', priceFormat: GEX_PRICE_FORMAT })
  netSeries = chart.addSeries(LineSeries, { ...commonOpts, color: COLOR_NET, title: 'Net', priceFormat: GEX_PRICE_FORMAT })
  // Sin priceScaleId -- por defecto cae en 'right', la misma escala que
  // Calls/Puts/Net. El valor que recibe (ver renderNetDriftChart) ya
  // viene reescalado por computeSpotTransform, no el precio real.
  spotSeries = chart.addSeries(LineSeries, { ...commonOpts, color: COLOR_ACCENT, title: 'Spot', priceFormat: SPOT_PRICE_FORMAT })

  // "Ola" de Net GEX en una franja propia abajo del panel (scaleMargins
  // de arriba le reserva el 22% inferior): BaselineSeries pinta el área
  // por encima de 0 de un color y por debajo de otro -- exactamente
  // verde cuando el neto es positivo, rojo cuando es negativo, sin tener
  // que armar dos series separadas a mano. Sin eje propio visible (es un
  // acento visual, no un dato que se lea por número ahí).
  netWaveSeries = chart.addSeries(BaselineSeries, {
    baseValue: { type: 'price', price: 0 },
    topLineColor: 'rgba(16, 185, 129, 0.9)',
    topFillColor1: 'rgba(16, 185, 129, 0.45)',
    topFillColor2: 'rgba(16, 185, 129, 0.05)',
    bottomLineColor: 'rgba(239, 68, 68, 0.9)',
    bottomFillColor1: 'rgba(239, 68, 68, 0.05)',
    bottomFillColor2: 'rgba(239, 68, 68, 0.45)',
    lineWidth: 2,
    priceScaleId: 'netWave',
    priceLineVisible: false,
    lastValueVisible: false,
    priceFormat: GEX_PRICE_FORMAT,
  })
  chart.priceScale('netWave').applyOptions({
    scaleMargins: { top: 0.8, bottom: 0.02 },
    visible: false,
  })

  resizeObserver = new ResizeObserver((entries) => {
    const { width, height } = entries[0].contentRect
    if (width > 0 && height > 0) chart.resize(width, height)
  })
  resizeObserver.observe(el)

  attachRightAxisWheelZoom(el)
}

/** Lightweight Charts deja hacer zoom vertical arrastrando el eje de
 * precio con el mouse (ahora nativo, ver handleScale en ensureChart),
 * pero la rueda del mouse SOLO controla el eje de tiempo -- no hay forma
 * nativa de usar scroll para zoom vertical, que es el gesto que se
 * espera viniendo de TradingView. Esto lo agrega a mano sobre el eje
 * derecho: al desactivar el autoScale con setAutoScale(false), el rango
 * manual sobrevive a los refrescos periódicos (cada renderNetDriftChart
 * vuelve a llamar setData, que no pisa un autoScale ya en false). */
function attachRightAxisWheelZoom(el) {
  el.addEventListener(
    'wheel',
    (event) => {
      if (!chart) return
      const rightScale = chart.priceScale('right')
      const scaleWidth = rightScale.width()
      if (scaleWidth <= 0) return

      const rect = el.getBoundingClientRect()
      const overRightAxis = event.clientX - rect.left >= rect.width - scaleWidth
      if (!overRightAxis) return

      // Lightweight Charts maneja el scroll con SU PROPIO listener sobre
      // un canvas interno (para su zoom de tiempo por defecto,
      // handleScale.mouseWheel) -- en fase de burbuja normal, ese
      // listener interno corre ANTES de llegar hasta acá, así que el
      // scroll sobre el eje terminaba haciendo zoom horizontal en vez
      // de vertical. Escuchando en fase de CAPTURA (capture: true) este
      // handler corre primero, y stopPropagation/stopImmediatePropagation
      // evita que el evento llegue al listener interno de la librería
      // una vez que ya lo procesamos acá.
      event.preventDefault()
      event.stopPropagation()
      event.stopImmediatePropagation()

      // getVisibleRange() puede devolver null (así lo documentan los
      // propios typings de la librería) -- lastRightDataRange, calculado
      // directo de los datos reales en cada render, es el respaldo.
      const range = rightScale.getVisibleRange() ?? lastRightDataRange
      if (!range) return

      // Scroll hacia arriba (deltaY < 0) acerca (achica el rango visible).
      const zoomFactor = event.deltaY < 0 ? 0.9 : 1 / 0.9
      const center = (range.from + range.to) / 2
      const halfSpan = ((range.to - range.from) / 2) * zoomFactor
      rightScale.setAutoScale(false)
      rightScale.setVisibleRange({ from: center - halfSpan, to: center + halfSpan })
    },
    { capture: true, passive: false },
  )
}

/** dateStr: la fecha (YYYY-MM-DD) seleccionada en el picker -- necesaria
 * para convertir los "HH:MM" de la serie a timestamps reales. */
export function renderNetDriftChart(el, series, dateStr) {
  if (!series.time || series.time.length === 0) return
  ensureChart(el)

  const times = series.time.map((t) => nyWallClockToUtcSeconds(dateStr, t))
  const callsValues = series.call_gex.map((v) => Math.abs(v))
  const putsValues = series.put_gex.map((v) => Math.abs(v))

  lastRightDataRange = rangeFromValues([...callsValues, ...putsValues, ...series.net_gex])
  spotTransform = computeSpotTransform(series.spot, lastRightDataRange)
  const spotChartValues = spotTransform
    ? series.spot.map((v) => toChartValue(v, spotTransform))
    : series.spot

  callsSeries.setData(times.map((time, i) => ({ time, value: callsValues[i] })))
  putsSeries.setData(times.map((time, i) => ({ time, value: putsValues[i] })))
  netSeries.setData(times.map((time, i) => ({ time, value: series.net_gex[i] })))
  spotSeries.setData(times.map((time, i) => ({ time, value: spotChartValues[i] })))
  netWaveSeries.setData(times.map((time, i) => ({ time, value: series.net_gex[i] })))

  chart.timeScale().fitContent()
}
