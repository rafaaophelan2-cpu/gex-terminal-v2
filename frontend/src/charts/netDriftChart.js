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
    // price: false en AMBOS -- el arrastre y el doble-click-reset
    // nativos de la librería solo tocan UN eje de precio a la vez (el
    // que esté bajo el mouse), así que arrastrando el derecho se movía
    // Calls/Puts/Net pero no Spot (su propia escala izquierda), y lo
    // mismo con el doble click. Se desactivan los dos acá y se
    // reimplementan a mano en attachSyncedAxisDrag (más abajo) aplicando
    // siempre el mismo cambio a 'right' y 'left' juntos, sin importar
    // desde qué eje arrancó el gesto -- así las 4 líneas (Calls/Puts/Net
    // arriba, Spot abajo) se mueven siempre en conjunto.
    handleScale: {
      axisPressedMouseMove: { time: true, price: false },
      axisDoubleClickReset: { time: true, price: false },
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
  attachSyncedAxisDrag(el)
}

/** Aplica un zoom relativo a 'baseRange' (no al rango ACTUAL del
 * priceScale) -- se pasa explícito en vez de leerlo con
 * getVisibleRange() adentro porque attachSyncedAxisDrag necesita que el
 * factor de cada movimiento del mouse se calcule siempre contra el
 * rango que había al EMPEZAR el arrastre, no contra el del frame
 * anterior (si no, el zoom se acumularía de forma no lineal y quedaría
 * carreado/tembloroso). El wheel handler, en cambio, sí quiere
 * incremental por cada "tick" de scroll -- por eso zoomPriceScale sigue
 * existiendo como un caso particular de esto con baseRange = rango
 * actual. */
function applyZoomFromBaseRange(priceScale, baseRange, factor) {
  if (!baseRange) return
  const center = (baseRange.from + baseRange.to) / 2
  const halfSpan = ((baseRange.to - baseRange.from) / 2) * factor
  priceScale.setAutoScale(false)
  priceScale.setVisibleRange({ from: center - halfSpan, to: center + halfSpan })
}

function zoomPriceScale(priceScale, zoomFactor) {
  applyZoomFromBaseRange(priceScale, priceScale.getVisibleRange(), zoomFactor)
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

function isOverPriceAxis(el, clientX) {
  if (!chart) return false
  const rightWidth = chart.priceScale('right').width()
  const leftWidth = chart.priceScale('left').width()
  if (rightWidth <= 0 && leftWidth <= 0) return false

  const rect = el.getBoundingClientRect()
  const x = clientX - rect.left
  return (rightWidth > 0 && x >= rect.width - rightWidth) || (leftWidth > 0 && x <= leftWidth)
}

/** Corre 'baseRange' verticalmente por 'priceDelta' (mismo ancho/span, solo
 * cambia la posición) -- a diferencia de applyZoomFromBaseRange (que
 * estira/achica el rango), esto es un PAN: el usuario aclaró que el
 * arrastre no debe "zoomear", debe simplemente mover la vista. */
function applyPanFromBaseRange(priceScale, baseRange, priceDelta) {
  if (!baseRange) return
  priceScale.setAutoScale(false)
  priceScale.setVisibleRange({ from: baseRange.from + priceDelta, to: baseRange.to + priceDelta })
}

/** El pedido explícito del usuario: el arrastre del eje de precio SIEMPRE
 * debe poder mover el gráfico (no bloquearlo, como un intento anterior
 * de este fix hacía) -- pero moviendo las 4 líneas (Calls/Puts/Net en
 * 'right', Spot en 'left') exactamente igual, sin importar si el
 * arrastre arrancó sobre el eje derecho o el izquierdo. La librería no
 * tiene esto de fábrica (cada priceScale se arrastra de forma
 * independiente, ver handleScale en ensureChart), así que se reimplementa
 * a mano: se mide el desplazamiento del mouse desde el mousedown y se
 * corre (PAN, no zoom -- ver applyPanFromBaseRange) el rango de 'right' y
 * 'left' por la misma proporción a la vez, contra el rango que cada uno
 * tenía al EMPEZAR el arrastre (no incremental por frame, para que no se
 * acumule de forma no lineal). El zoom (estirar/achicar el rango) sigue
 * siendo solo cosa de la rueda del mouse (attachRightAxisWheelZoom) -- el
 * usuario aclaró que "arrastrar" debe mover la vista, no escalarla. La
 * "ola" de abajo (netWaveSeries, su propia escala 'netWave') nunca se
 * toca acá -- se queda fija como pidió el usuario.
 *
 * Confirmado en la práctica (no solo en teoría): handleScale.
 * axisPressedMouseMove.price:false NO alcanza por sí solo para
 * desactivar el arrastre nativo de la librería una vez que ya se llamó
 * setAutoScale(false) alguna vez (con el wheel-zoom, por ejemplo) -- la
 * librería lo sigue procesando igual. Mientras tanto siga recibiendo
 * estos eventos, sigue reescalando por su cuenta el eje que se esté
 * agarrando con el mouse, pisando visualmente el zoom sincronizado de
 * acá abajo (por eso "solo se movía Spot/QQQ": la librería reescalaba
 * nomás el eje bajo el mouse en cada mousemove, mientras este código
 * trataba de mover los dos a la vez). Por eso mousedown Y mousemove se
 * cortan en fase de CAPTURA antes de que le lleguen al canvas interno
 * -- la librería nunca se entera de que hubo un drag, así que no tiene
 * forma de reaccionar por su cuenta. El doble click para resetear (ver
 * más abajo) no depende de que la librería reciba estos eventos -- es
 * el evento 'dblclick' nativo del navegador, independiente de esto. */
function attachSyncedAxisDrag(el) {
  let dragging = false
  let dragStartY = 0
  let dragStartHeightPx = 0
  let dragStartRightRange = null
  let dragStartLeftRange = null

  el.addEventListener(
    'mousedown',
    (event) => {
      if (!isOverPriceAxis(el, event.clientX)) return
      dragging = true
      dragStartY = event.clientY
      dragStartHeightPx = el.getBoundingClientRect().height
      dragStartRightRange = chart.priceScale('right').getVisibleRange()
      dragStartLeftRange = chart.priceScale('left').getVisibleRange()
      event.preventDefault()
      event.stopPropagation()
      event.stopImmediatePropagation()
    },
    { capture: true },
  )

  // En window (no en 'el'): así el arrastre sigue funcionando aunque el
  // mouse se salga del área del gráfico durante el gesto, y al estar en
  // fase de CAPTURA sobre el nodo más alto de todos, este handler corre
  // ANTES que cualquier listener interno de la librería cuando el mouse
  // sí está sobre el chart -- stopPropagation ahí corta el evento antes
  // de que baje hasta el canvas.
  window.addEventListener(
    'mousemove',
    (event) => {
      if (!dragging || !chart) return
      if (event.buttons === 0) {
        dragging = false
        return
      }
      event.preventDefault()
      event.stopPropagation()
      event.stopImmediatePropagation()

      if (dragStartHeightPx <= 0) return
      const deltaY = event.clientY - dragStartY
      // Un mismo desplazamiento en pixeles representa una cantidad de
      // PRECIO distinta en cada eje (Calls/Puts/Net están en millones,
      // Spot en dólares) -- por eso el delta se calcula por separado
      // para cada uno, como fracción de su propio span (rango visible al
      // empezar el arrastre) sobre el alto del panel, no un valor fijo
      // en dólares/millones. Arrastrar hacia abajo (deltaY > 0) sube el
      // techo del rango visible (revela valores más altos, como al
      // arrastrar una regla larga hacia abajo con el dedo); si se siente
      // invertido en la práctica, alcanza con invertir el signo acá.
      if (dragStartRightRange) {
        const spanRight = dragStartRightRange.to - dragStartRightRange.from
        applyPanFromBaseRange(chart.priceScale('right'), dragStartRightRange, (deltaY / dragStartHeightPx) * spanRight)
      }
      if (dragStartLeftRange) {
        const spanLeft = dragStartLeftRange.to - dragStartLeftRange.from
        applyPanFromBaseRange(chart.priceScale('left'), dragStartLeftRange, (deltaY / dragStartHeightPx) * spanLeft)
      }
    },
    { capture: true, passive: false },
  )

  window.addEventListener('mouseup', () => {
    dragging = false
  })

  // Reemplaza axisDoubleClickReset.price (desactivado en ensureChart): el
  // reset nativo solo resetea el eje bajo el mouse, dejando al otro
  // todavía con zoom manual -- otra vía más de desincronización. Acá el
  // doble click sobre cualquiera de los dos ejes resetea AMBOS al
  // autoScale a la vez.
  el.addEventListener('dblclick', (event) => {
    if (!chart || !isOverPriceAxis(el, event.clientX)) return
    chart.priceScale('right').applyOptions({ autoScale: true })
    chart.priceScale('left').applyOptions({ autoScale: true })
  })
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
