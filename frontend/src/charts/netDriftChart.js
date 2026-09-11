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
    leftPriceScale: {
      visible: true, borderColor: 'rgba(255,255,255,0.1)', scaleMargins: { top: 0.05, bottom: 0.25 },
    },
    crosshair: { mode: 0 },
    // price: false -- el arrastre nativo de la librería solo escala UN
    // eje de precio a la vez (el que se esté arrastrando), así que
    // arrastrando el derecho movía Calls/Puts/Net pero no Spot (su
    // propia escala izquierda), quedando "desincronizado" igual que
    // pasaba antes con la rueda del mouse. El scroll (ver
    // attachRightAxisWheelZoom más abajo) ya hace zoom vertical
    // sincronizado en ambos ejes a la vez, así que el arrastre del eje
    // se desactiva del todo en vez de dejar ese camino roto.
    handleScale: {
      axisPressedMouseMove: { time: true, price: false },
      axisDoubleClickReset: { time: true, price: true },
      mouseWheel: true,
      pinch: true,
    },
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

function zoomPriceScale(priceScale, zoomFactor) {
  const range = priceScale.getVisibleRange()
  if (!range) return
  const center = (range.from + range.to) / 2
  const halfSpan = ((range.to - range.from) / 2) * zoomFactor
  priceScale.setAutoScale(false)
  priceScale.setVisibleRange({ from: center - halfSpan, to: center + halfSpan })
}

/** Lightweight Charts deja hacer zoom vertical arrastrando el eje de
 * precio con el mouse (axisPressedMouseMove.price, prendido por
 * defecto), pero la rueda del mouse SOLO controla el eje de tiempo --
 * no hay forma nativa de usar scroll para zoom vertical, que es el
 * gesto que se espera viniendo de TradingView. Esto lo agrega a mano
 * sobre el eje derecho (Calls/Puts/Net): al desactivar el autoScale con
 * setAutoScale(false), el rango manual sobrevive a los refrescos
 * periódicos (cada renderNetDriftChart vuelve a llamar setData, que no
 * pisa un autoScale ya en false) -- doble click sobre el eje lo resetea
 * (axisDoubleClickReset.price, también por defecto).
 *
 * Zoomea el eje IZQUIERDO (Spot) al mismo tiempo y con el mismo factor:
 * Spot vive en su propia escala (rango ~$700, muy distinto a los
 * millones de Calls/Puts/Net) justamente para que sea visible al lado
 * de series de otra magnitud -- pero al ser dos escalas independientes,
 * zoomear solo la derecha dejaba a Spot totalmente quieto mientras las
 * otras tres líneas sí se movían, que es justo lo que se veía "roto". */
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
      // de vertical (los dos zooms competían, y el de la librería
      // ganaba visualmente). Escuchando en fase de CAPTURA (capture:
      // true) este handler corre primero, y stopPropagation/
      // stopImmediatePropagation evita que el evento llegue al listener
      // interno de la librería una vez que ya lo procesamos acá.
      event.preventDefault()
      event.stopPropagation()
      event.stopImmediatePropagation()

      // Scroll hacia arriba (deltaY < 0) acerca (achica el rango visible).
      const zoomFactor = event.deltaY < 0 ? 0.9 : 1 / 0.9
      zoomPriceScale(rightScale, zoomFactor)
      zoomPriceScale(chart.priceScale('left'), zoomFactor)
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

  callsSeries.setData(times.map((time, i) => ({ time, value: Math.abs(series.call_gex[i]) })))
  putsSeries.setData(times.map((time, i) => ({ time, value: Math.abs(series.put_gex[i]) })))
  netSeries.setData(times.map((time, i) => ({ time, value: series.net_gex[i] })))
  spotSeries.setData(times.map((time, i) => ({ time, value: series.spot[i] })))
  netWaveSeries.setData(times.map((time, i) => ({ time, value: series.net_gex[i] })))

  chart.timeScale().fitContent()
}
