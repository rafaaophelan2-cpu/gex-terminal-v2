import './style.css'
import { marked } from 'marked'
import { login, logout, me } from './api/auth.js'
import { clearChatHistory, fetchChatHistory, postChatMessage } from './api/chat.js'
import { fetchAvailableDates, fetchCandles, fetchDrift, fetchExpirations, fetchGammaGrid, fetchHeatmap, fetchVix, postAiDiagnosis } from './api/rest.js'
import { MarketWebSocketClient } from './api/ws.js'
import { renderBackgammaSpotChart, renderBackgammaStrikeChart } from './charts/backgammaChart.js'
import { renderGammaGridTable } from './charts/gammaGridTable.js'
import { renderGammaVolumeProfile } from './charts/gammaVolumeProfile.js'
import { renderChainFull, resetGexInfoChart, updateTick } from './charts/gexInfoChart.js'
import { renderGreeksChart, resetGreeksChart } from './charts/greeksChart.js'
import { renderLiveGammaChart } from './charts/liveGammaChart.js'
import { renderNetDriftChart } from './charts/netDriftChart.js'
import { fmtMoney } from './utils/format.js'

const loginView = document.getElementById('login-view')
const dashboardView = document.getElementById('dashboard-view')
const loginForm = document.getElementById('login-form')
const loginError = document.getElementById('login-error')
const userBadge = document.getElementById('user-badge')
const wsStatusEl = document.getElementById('ws-status')
const logoutBtn = document.getElementById('logout-btn')
const chartEl = document.getElementById('gex-info-chart')
const symbolInput = document.getElementById('symbol-input')
const strikeRangeInput = document.getElementById('strike-range-input')
const applySymbolBtn = document.getElementById('apply-symbol-btn')
const tabButtons = document.querySelectorAll('#tab-nav .tab-btn')
const greeksChartEl = document.getElementById('greeks-chart')
const greeksSubNavButtons = document.querySelectorAll('#greeks-sub-nav .tab-btn')
const netDriftChartEl = document.getElementById('net-drift-chart')
const driftDateInput = document.getElementById('drift-date-input')
const liveGammaChartEl = document.getElementById('live-gamma-chart')
const backgammaDateSelect = document.getElementById('backgamma-date-select')
const backgammaPlayBtn = document.getElementById('backgamma-play-btn')
const backgammaSpeedSelect = document.getElementById('backgamma-speed-select')
const backgammaScrubber = document.getElementById('backgamma-scrubber')
const backgammaCaption = document.getElementById('backgamma-caption')
const backgammaSpotChartEl = document.getElementById('backgamma-spot-chart')
const backgammaStrikeChartEl = document.getElementById('backgamma-strike-chart')
const aiTipoSelect = document.getElementById('ai-tipo-select')
const aiDiagnosisBtn = document.getElementById('ai-diagnosis-btn')
const aiStatusEl = document.getElementById('ai-status')
const aiResultEl = document.getElementById('ai-diagnosis-result')
const chatToggleBtn = document.getElementById('chat-toggle-btn')
const chatPanel = document.getElementById('chat-panel')
const chatCloseBtn = document.getElementById('chat-close-btn')
const chatClearBtn = document.getElementById('chat-clear-btn')
const chatMessagesEl = document.getElementById('chat-messages')
const chatForm = document.getElementById('chat-form')
const chatInput = document.getElementById('chat-input')
const chatSendBtn = document.getElementById('chat-send-btn')
const gridDteBtn = document.getElementById('grid-dte-btn')
const gridDteCount = document.getElementById('grid-dte-count')
const gridDtePanel = document.getElementById('grid-dte-panel')
const gridDteList = document.getElementById('grid-dte-list')
const gridDteApplyBtn = document.getElementById('grid-dte-apply-btn')
const gridStatusEl = document.getElementById('grid-status')
const gammaGridTableEl = document.getElementById('gamma-grid-table')
const gammaVolumeProfileEl = document.getElementById('gamma-volume-profile')

const dataMetricEls = {
  regime: document.getElementById('data-regime'),
  netGex: document.getElementById('data-net-gex'),
  zg: document.getElementById('data-zg'),
  cw1: document.getElementById('data-cw1'),
  pw1: document.getElementById('data-pw1'),
  dex: document.getElementById('data-dex'),
  tex: document.getElementById('data-tex'),
  vex: document.getElementById('data-vex'),
  chex: document.getElementById('data-chex'),
  vanna: document.getElementById('data-vanna'),
  iv: document.getElementById('data-iv'),
  ivRank: document.getElementById('data-iv-rank'),
}

const greeksMetricEls = {
  dex: document.getElementById('greeks-dex'),
  tex: document.getElementById('greeks-tex'),
  vex: document.getElementById('greeks-vex'),
  chex: document.getElementById('greeks-chex'),
  vanna: document.getElementById('greeks-vanna'),
}

const metricEls = {
  symbol: document.getElementById('metric-symbol'),
  spot: document.getElementById('metric-spot'),
  netGex: document.getElementById('metric-net-gex'),
  callGex: document.getElementById('metric-call-gex'),
  putGex: document.getElementById('metric-put-gex'),
  cw1: document.getElementById('metric-cw1'),
  pw1: document.getElementById('metric-pw1'),
  zg: document.getElementById('metric-zg'),
  vix: document.getElementById('metric-vix'),
  vixStatus: document.getElementById('metric-vix-status'),
}

let wsClient = null
let chatHistoryLoaded = false
let activeGreek = 'dex'
let latestGreeksPayload = null
let latestGexInfo = null
let latestWalls = null
let driftRefreshTimer = null
let driftDateAutoSelected = true
let liveGammaRefreshTimer = null
let vixRefreshTimer = null
let backgammaHeatmap = null
let backgammaPlayTimer = null
let gridExpirations = []
let gridSelectedExpKeys = null
let gridRefreshTimer = null

const DRIFT_REFRESH_MS = 30000
const LIVE_GAMMA_REFRESH_MS = 30000
const VIX_REFRESH_MS = 30000
const GRID_REFRESH_MS = 15000

function isGreeksTabActive() {
  return document.getElementById('tab-greeks').classList.contains('active')
}

function todayInLima() {
  // Lima (UTC-5) no observa horario de verano, así que un formateo con
  // Intl alcanza sin necesitar una librería de fechas.
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Lima' }).format(new Date())
}

async function loadNetDrift() {
  try {
    const symbol = symbolInput.value.trim().toUpperCase() || 'QQQ'
    const date = driftDateInput.value || todayInLima()
    const series = await fetchDrift(symbol, date)
    renderNetDriftChart(netDriftChartEl, series, date)
  } catch (err) {
    console.error('Error cargando NET DRIFT:', err)
  }
}

async function driftRefreshTick() {
  // Si el usuario no eligió una fecha a mano, cada refresh vuelve a
  // resolver "la última sesión" -- así, si el mercado abre mientras la
  // pestaña ya está abierta (mostrando la sesión anterior por defecto),
  // NET DRIFT salta solo a la sesión nueva apenas aparece el primer
  // snapshot, sin necesitar recargar la página. Si el usuario SÍ eligió
  // una fecha manualmente, se respeta esa elección (no se pisa).
  if (driftDateAutoSelected) {
    try {
      const symbol = symbolInput.value.trim().toUpperCase() || 'QQQ'
      const dates = await fetchAvailableDates(symbol)
      if (dates[0] && dates[0] !== driftDateInput.value) {
        driftDateInput.value = dates[0]
      }
    } catch (err) {
      console.error('Error resolviendo última sesión de NET DRIFT:', err)
    }
  }
  await loadNetDrift()
}

function startDriftRefresh() {
  stopDriftRefresh()
  driftRefreshTick()
  driftRefreshTimer = setInterval(driftRefreshTick, DRIFT_REFRESH_MS)
}

function stopDriftRefresh() {
  if (driftRefreshTimer) {
    clearInterval(driftRefreshTimer)
    driftRefreshTimer = null
  }
}

async function loadLiveGamma() {
  try {
    const symbol = symbolInput.value.trim().toUpperCase() || 'QQQ'
    // LIVE GAMMA no usa el selector de fecha de NET DRIFT -- siempre
    // resuelve sola la última sesión disponible (available-dates ya
    // viene ordenado por más reciente, solo fechas con datos reales:
    // cubre tanto "todavía no abrió hoy" como "ya cerró hoy" sin
    // depender de qué fecha haya elegido el usuario en otra pestaña).
    const dates = await fetchAvailableDates(symbol)
    const date = dates[0] || todayInLima()
    const [heatmap, candles] = await Promise.all([
      fetchHeatmap(symbol, date),
      fetchCandles(symbol, date).catch(() => []),
    ])
    renderLiveGammaChart(liveGammaChartEl, heatmap, latestWalls, candles, date)
  } catch (err) {
    console.error('Error cargando LIVE GAMMA:', err)
  }
}

function startLiveGammaRefresh() {
  stopLiveGammaRefresh()
  loadLiveGamma()
  liveGammaRefreshTimer = setInterval(loadLiveGamma, LIVE_GAMMA_REFRESH_MS)
}

async function loadVix() {
  try {
    const vix = await fetchVix()
    setMetric(metricEls.vix, vix.value ? vix.value.toFixed(2) : '--', null)
    metricEls.vix.style.color = vix.color || '#f0f6fc'
    metricEls.vixStatus.textContent = vix.status || ''
  } catch (err) {
    console.error('Error cargando VIX:', err)
  }
}

function startVixRefresh() {
  stopVixRefresh()
  loadVix()
  vixRefreshTimer = setInterval(loadVix, VIX_REFRESH_MS)
}

function stopVixRefresh() {
  if (vixRefreshTimer) {
    clearInterval(vixRefreshTimer)
    vixRefreshTimer = null
  }
}

function stopLiveGammaRefresh() {
  if (liveGammaRefreshTimer) {
    clearInterval(liveGammaRefreshTimer)
    liveGammaRefreshTimer = null
  }
}

function renderDteChecklist() {
  if (gridExpirations.length === 0) {
    gridDteList.innerHTML = '<p class="dte-list-placeholder">Sin expiraciones disponibles -- abre GEX INFO primero.</p>'
    return
  }
  // Antes de la primera selección manual, se marcan las mismas
  // expiraciones por defecto que ya aplicó el backend (nearest-DTE en
  // adelante) -- ver DEFAULT_GRID_EXPIRATION_COUNT en routes_rest.py.
  const checkedKeys = gridSelectedExpKeys ?? gridExpirations.slice(0, 6).map((e) => e.exp_key)
  gridDteList.innerHTML = gridExpirations
    .map((exp) => {
      const checked = checkedKeys.includes(exp.exp_key) ? 'checked' : ''
      return `<label class="dte-item"><input type="checkbox" value="${exp.exp_key}" ${checked} /> ${exp.exp_date} · ${exp.dte} DTE</label>`
    })
    .join('')
}

async function loadGridExpirations() {
  try {
    const symbol = symbolInput.value.trim().toUpperCase() || 'QQQ'
    gridExpirations = await fetchExpirations(symbol)
    renderDteChecklist()
  } catch (err) {
    console.error('Error cargando expiraciones del GRID:', err)
  }
}

function openGridDtePanel() {
  gridDtePanel.hidden = false
  if (gridExpirations.length === 0) loadGridExpirations()
}

function closeGridDtePanel() {
  gridDtePanel.hidden = true
}

function applyGridDteSelection() {
  const checked = Array.from(gridDteList.querySelectorAll('input[type="checkbox"]:checked'))
  gridSelectedExpKeys = checked.map((cb) => cb.value)
  gridDteCount.textContent = gridSelectedExpKeys.length > 0 ? `(${gridSelectedExpKeys.length})` : ''
  closeGridDtePanel()
  loadGammaGrid()
}

async function loadGammaGrid() {
  try {
    const symbol = symbolInput.value.trim().toUpperCase() || 'QQQ'
    gridStatusEl.textContent = 'Actualizando…'
    const grid = await fetchGammaGrid(symbol, gridSelectedExpKeys)
    renderGammaGridTable(gammaGridTableEl, grid)
    renderGammaVolumeProfile(gammaVolumeProfileEl, grid)

    // Si todavía no hubo selección manual, adopta las columnas que el
    // backend eligió por defecto -- así el selector de DTEs, al abrirse,
    // muestra marcado exactamente lo que ya se está viendo.
    if (gridSelectedExpKeys === null && grid.columns) {
      gridSelectedExpKeys = grid.columns.map((c) => c.exp_key)
      gridDteCount.textContent = `(${gridSelectedExpKeys.length})`
    }
    gridStatusEl.textContent = `Actualizado ${new Date().toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`
  } catch (err) {
    gridStatusEl.textContent = err.message || 'Error cargando el GRID.'
    console.error('Error cargando GRID de gamma:', err)
  }
}

function startGridRefresh() {
  stopGridRefresh()
  loadGammaGrid()
  gridRefreshTimer = setInterval(loadGammaGrid, GRID_REFRESH_MS)
}

function stopGridRefresh() {
  if (gridRefreshTimer) {
    clearInterval(gridRefreshTimer)
    gridRefreshTimer = null
  }
}

function renderBackgammaAtIndex(index) {
  if (!backgammaHeatmap || !backgammaHeatmap.times.length) return
  const i = Math.min(Math.max(index, 0), backgammaHeatmap.times.length - 1)
  renderBackgammaSpotChart(backgammaSpotChartEl, backgammaHeatmap, i)
  renderBackgammaStrikeChart(backgammaStrikeChartEl, backgammaHeatmap, i)
  backgammaCaption.textContent = `${backgammaDateSelect.value}  ${backgammaHeatmap.times[i]}  ·  paso ${i + 1}/${backgammaHeatmap.times.length}`
}

async function loadBackgammaDates() {
  try {
    const symbol = symbolInput.value.trim().toUpperCase() || 'QQQ'
    const dates = await fetchAvailableDates(symbol)
    backgammaDateSelect.innerHTML = ''
    dates.forEach((d) => {
      const opt = document.createElement('option')
      opt.value = d
      opt.textContent = d
      backgammaDateSelect.appendChild(opt)
    })
    if (dates.length > 0) {
      await loadBackgammaDay(dates[0])
    }
  } catch (err) {
    console.error('Error cargando fechas de BACKGAMMA:', err)
  }
}

async function loadBackgammaDay(date) {
  try {
    stopBackgammaPlay()
    const symbol = symbolInput.value.trim().toUpperCase() || 'QQQ'
    backgammaHeatmap = await fetchHeatmap(symbol, date)
    const lastIndex = Math.max(backgammaHeatmap.times.length - 1, 0)
    backgammaScrubber.max = String(lastIndex)
    backgammaScrubber.value = String(lastIndex)
    renderBackgammaAtIndex(lastIndex)
  } catch (err) {
    console.error('Error cargando día de BACKGAMMA:', err)
  }
}

function stopBackgammaPlay() {
  if (backgammaPlayTimer) {
    clearInterval(backgammaPlayTimer)
    backgammaPlayTimer = null
  }
  backgammaPlayBtn.textContent = '▶ Reproducir'
  backgammaPlayBtn.classList.remove('playing')
}

async function setDefaultDriftDate() {
  if (driftDateInput.value) return
  try {
    // La "última sesión" real no es necesariamente "hoy": si todavía no
    // abrió el mercado (ej. la 1am), hoy no tiene datos de horario de
    // mercado todavía. available-dates ya está ordenado por más reciente
    // primero y solo incluye días con datos guardados de verdad, así que
    // usar el primero cubre ambos casos sin adivinar con el reloj.
    const symbol = symbolInput.value.trim().toUpperCase() || 'QQQ'
    const dates = await fetchAvailableDates(symbol)
    driftDateInput.value = dates[0] || todayInLima()
  } catch {
    driftDateInput.value = todayInLima()
  }
}

function showDashboard(username) {
  loginView.hidden = true
  dashboardView.hidden = false
  sessionExpiredHandled = false
  userBadge.textContent = `👤 ${username}`
  resetGexInfoChart()
  resetGreeksChart()
  setDefaultDriftDate()
  connectMarketFeed()
  startVixRefresh()
}

function showLogin() {
  loginView.hidden = false
  dashboardView.hidden = true
  wsClient?.close()
  // Se detienen TODOS los refrescos periódicos sin importar en qué
  // pestaña estaba el usuario -- antes solo el cambio de pestaña los
  // paraba, así que si la sesión expiraba (ver 'session-expired' más
  // abajo) mientras, por ejemplo, LIVE GAMMA seguía activo, ese timer
  // quedaba reintentando en un loop de errores 401 indefinidamente.
  stopVixRefresh()
  stopDriftRefresh()
  stopLiveGammaRefresh()
  stopBackgammaPlay()
  stopGridRefresh()
  gridExpirations = []
  gridSelectedExpKeys = null
  chatHistoryLoaded = false
  chatMessagesEl.innerHTML = '<p class="chat-placeholder">Pregunta sobre VIX, GEX, Griegas o niveles de mercado del símbolo activo.</p>'
  closeChatPanel()
}

function setMetric(el, text, valueClass) {
  el.textContent = text
  el.className = valueClass ? `metric-value ${valueClass}` : 'metric-value'
}

function setWsStatus(status) {
  const labels = {
    connecting: 'conectando…',
    connected: 'en vivo',
    reconnecting: 'reconectando…',
    disconnected: 'desconectado',
  }
  wsStatusEl.textContent = labels[status] || status
  wsStatusEl.className = `status-pill status-${status}`
}

function updateDataSummary() {
  if (!latestGexInfo) return
  const netGex = latestGexInfo.net_gex_total
  const isPositive = netGex >= 0
  const signClass = (v) => (v >= 0 ? 'val-positive' : 'val-negative')

  setMetric(dataMetricEls.regime, isPositive ? 'POSITIVO (mean-reverting)' : 'NEGATIVO (trending)', signClass(netGex))
  setMetric(dataMetricEls.netGex, fmtMoney(netGex), signClass(netGex))
  setMetric(dataMetricEls.zg, latestGexInfo.flip_level ? `$${latestGexInfo.flip_level.toFixed(2)}` : '--', 'val-zero-gamma')
  setMetric(dataMetricEls.cw1, latestGexInfo.walls?.cw1 ? `$${latestGexInfo.walls.cw1.toFixed(0)}` : '--', 'val-call-wall')
  setMetric(dataMetricEls.pw1, latestGexInfo.walls?.pw1 ? `$${latestGexInfo.walls.pw1.toFixed(0)}` : '--', 'val-put-wall')
  setMetric(dataMetricEls.iv, latestGexInfo.iv_str || '--', null)
  dataMetricEls.ivRank.textContent = latestGexInfo.iv_rank_str || ''

  if (latestGreeksPayload) {
    const t = latestGreeksPayload.totals
    setMetric(dataMetricEls.dex, `${t.dex.toFixed(2)}M`, signClass(t.dex))
    setMetric(dataMetricEls.tex, fmtMoney(t.tex), signClass(t.tex))
    setMetric(dataMetricEls.vex, fmtMoney(t.vex), signClass(t.vex))
    setMetric(dataMetricEls.chex, `${t.chex.toFixed(2)}M`, signClass(t.chex))
    setMetric(dataMetricEls.vanna, `${t.vanna.toFixed(2)}M`, signClass(t.vanna))
  }
}

function handleMarketMessage(data) {
  if (data.type === 'pong') return

  if (data.type === 'chain_full' || data.type === 'tick') {
    metricEls.symbol.textContent = data.symbol
    setMetric(metricEls.spot, data.spot ? `$${data.spot.toFixed(2)}` : '--', 'val-spot')
    const info = data.gex_info
    latestGexInfo = info
    // zero_gamma se agrega acá (no viene dentro de info.walls) para que
    // LIVE GAMMA pueda dibujar también la línea de Gamma Flip con el
    // mismo objeto que ya usa para Call/Put Walls.
    latestWalls = { ...info.walls, zero_gamma: info.flip_level }
    setMetric(metricEls.netGex, fmtMoney(info.net_gex_total), info.net_gex_total >= 0 ? 'val-positive' : 'val-negative')
    setMetric(metricEls.callGex, fmtMoney(info.call_gex_total), info.call_gex_total >= 0 ? 'val-positive' : 'val-negative')
    setMetric(metricEls.putGex, fmtMoney(info.put_gex_total), info.put_gex_total >= 0 ? 'val-positive' : 'val-negative')
    setMetric(metricEls.cw1, info.walls?.cw1 ? `$${info.walls.cw1.toFixed(0)}` : '--', 'val-call-wall')
    setMetric(metricEls.pw1, info.walls?.pw1 ? `$${info.walls.pw1.toFixed(0)}` : '--', 'val-put-wall')
    setMetric(metricEls.zg, info.flip_level ? `$${info.flip_level.toFixed(2)}` : '--', 'val-zero-gamma')

    if (info.by_strike && info.by_strike.length > 0) {
      if (data.type === 'chain_full') {
        renderChainFull(chartEl, info, data.spot)
      } else {
        updateTick(chartEl, info, data.spot)
      }
    }

    if (data.greeks) {
      latestGreeksPayload = data.greeks
      const t = data.greeks.totals
      const signClass = (v) => (v >= 0 ? 'val-positive' : 'val-negative')
      setMetric(greeksMetricEls.dex, `${t.dex.toFixed(2)}M`, signClass(t.dex))
      setMetric(greeksMetricEls.tex, fmtMoney(t.tex), signClass(t.tex))
      setMetric(greeksMetricEls.vex, fmtMoney(t.vex), signClass(t.vex))
      setMetric(greeksMetricEls.chex, `${t.chex.toFixed(2)}M`, signClass(t.chex))
      setMetric(greeksMetricEls.vanna, `${t.vanna.toFixed(2)}M`, signClass(t.vanna))

      if (isGreeksTabActive()) {
        renderGreeksChart(greeksChartEl, activeGreek, data.greeks, data.type === 'chain_full')
      }
    }

    updateDataSummary()
  }
}

function connectMarketFeed() {
  wsClient?.close()
  wsClient = new MarketWebSocketClient({
    onMessage: handleMarketMessage,
    onStatusChange: setWsStatus,
  })
  wsClient.connect()
}

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault()
  loginError.hidden = true
  const username = document.getElementById('username').value
  const password = document.getElementById('password').value

  try {
    const result = await login(username, password)
    showDashboard(result.username)
  } catch (err) {
    loginError.textContent = err.message || 'Usuario o contraseña incorrectos.'
    loginError.hidden = false
  }
})

logoutBtn.addEventListener('click', async () => {
  await logout()
  showLogin()
})

backgammaDateSelect.addEventListener('change', () => {
  loadBackgammaDay(backgammaDateSelect.value)
})

backgammaScrubber.addEventListener('input', () => {
  stopBackgammaPlay()
  renderBackgammaAtIndex(parseInt(backgammaScrubber.value, 10))
})

backgammaPlayBtn.addEventListener('click', () => {
  if (backgammaPlayTimer) {
    stopBackgammaPlay()
    return
  }
  if (!backgammaHeatmap || backgammaHeatmap.times.length <= 1) return
  backgammaPlayBtn.textContent = '⏸ Pausar'
  backgammaPlayBtn.classList.add('playing')
  const speed = parseInt(backgammaSpeedSelect.value, 10) || 1000
  backgammaPlayTimer = setInterval(() => {
    const next = (parseInt(backgammaScrubber.value, 10) + 1) % (backgammaHeatmap.times.length)
    backgammaScrubber.value = String(next)
    renderBackgammaAtIndex(next)
  }, speed)
})

driftDateInput.addEventListener('change', () => {
  driftDateAutoSelected = false
  if (driftRefreshTimer) loadNetDrift()
})

applySymbolBtn.addEventListener('click', () => {
  const symbol = symbolInput.value.trim().toUpperCase() || 'QQQ'
  const strikeRange = Math.min(Math.max(parseInt(strikeRangeInput.value, 10) || 20, 5), 80)
  symbolInput.value = symbol
  strikeRangeInput.value = strikeRange
  resetGexInfoChart()
  wsClient?.subscribe(symbol, strikeRange)

  // Las expiraciones/selección del GRID son por símbolo -- al cambiar de
  // símbolo se descartan para que la próxima carga pida las del nuevo.
  gridExpirations = []
  gridSelectedExpKeys = null
  gridDteCount.textContent = ''
})

tabButtons.forEach((btn) => {
  btn.addEventListener('click', () => {
    tabButtons.forEach((b) => b.classList.remove('active'))
    document.querySelectorAll('.tab-panel').forEach((p) => p.classList.remove('active'))
    btn.classList.add('active')
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active')

    // Un chart de Plotly renderizado mientras su contenedor estaba oculto
    // (display:none) no mide bien el tamaño -- forzar un redraw completo
    // al hacerse visible por primera vez tras el cambio de pestaña.
    if (btn.dataset.tab === 'greeks' && latestGreeksPayload) {
      renderGreeksChart(greeksChartEl, activeGreek, latestGreeksPayload, true)
    }

    if (btn.dataset.tab === 'net-drift') {
      startDriftRefresh()
    } else {
      stopDriftRefresh()
    }

    if (btn.dataset.tab === 'live-gamma') {
      startLiveGammaRefresh()
    } else {
      stopLiveGammaRefresh()
    }

    if (btn.dataset.tab === 'backgamma') {
      if (!backgammaHeatmap) loadBackgammaDates()
    } else {
      stopBackgammaPlay()
    }

    if (btn.dataset.tab === 'grid') {
      startGridRefresh()
    } else {
      stopGridRefresh()
      closeGridDtePanel()
    }
  })
})

gridDteBtn.addEventListener('click', () => {
  if (gridDtePanel.hidden) openGridDtePanel()
  else closeGridDtePanel()
})

gridDteApplyBtn.addEventListener('click', applyGridDteSelection)

document.addEventListener('click', (event) => {
  if (!gridDtePanel.hidden && !event.target.closest('.dte-selector')) {
    closeGridDtePanel()
  }
})

greeksSubNavButtons.forEach((btn) => {
  btn.addEventListener('click', () => {
    greeksSubNavButtons.forEach((b) => b.classList.remove('active'))
    btn.classList.add('active')
    activeGreek = btn.dataset.greek
    if (latestGreeksPayload) {
      renderGreeksChart(greeksChartEl, activeGreek, latestGreeksPayload, true)
    }
  })
})

function scrollChatToBottom() {
  chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight
}

function clearChatPlaceholder() {
  const placeholder = chatMessagesEl.querySelector('.chat-placeholder')
  if (placeholder) placeholder.remove()
}

function appendChatMessage(role, content, { pending = false } = {}) {
  clearChatPlaceholder()
  const bubble = document.createElement('div')
  bubble.className = `chat-msg chat-msg-${role}${pending ? ' chat-msg-pending' : ''}`
  if (role === 'assistant') {
    bubble.innerHTML = marked.parse(content)
  } else {
    bubble.textContent = content
  }
  chatMessagesEl.appendChild(bubble)
  scrollChatToBottom()
  return bubble
}

async function loadChatHistory() {
  if (chatHistoryLoaded) return
  chatHistoryLoaded = true
  try {
    const messages = await fetchChatHistory()
    messages.forEach((m) => appendChatMessage(m.role, m.content))
  } catch (err) {
    console.error('Error cargando historial de chat:', err)
  }
}

function openChatPanel() {
  chatPanel.hidden = false
  loadChatHistory()
  chatInput.focus()
}

function closeChatPanel() {
  chatPanel.hidden = true
}

chatToggleBtn.addEventListener('click', () => {
  if (chatPanel.hidden) openChatPanel()
  else closeChatPanel()
})

chatCloseBtn.addEventListener('click', closeChatPanel)

chatClearBtn.addEventListener('click', async () => {
  try {
    await clearChatHistory()
    chatMessagesEl.innerHTML = '<p class="chat-placeholder">Pregunta sobre VIX, GEX, Griegas o niveles de mercado del símbolo activo.</p>'
  } catch (err) {
    console.error('Error limpiando historial de chat:', err)
  }
})

chatForm.addEventListener('submit', async (event) => {
  event.preventDefault()
  const message = chatInput.value.trim()
  if (!message) return

  const symbol = symbolInput.value.trim().toUpperCase() || 'QQQ'
  appendChatMessage('user', message)
  chatInput.value = ''
  chatInput.disabled = true
  chatSendBtn.disabled = true
  const pendingBubble = appendChatMessage('assistant', 'Pensando…', { pending: true })

  try {
    const result = await postChatMessage(symbol, message)
    pendingBubble.remove()
    appendChatMessage('assistant', result.content)
  } catch (err) {
    pendingBubble.remove()
    appendChatMessage('assistant', `⚠ ${err.message || 'Error generando la respuesta.'}`)
  } finally {
    chatInput.disabled = false
    chatSendBtn.disabled = false
    chatInput.focus()
  }
})

aiDiagnosisBtn.addEventListener('click', async () => {
  const symbol = symbolInput.value.trim().toUpperCase() || 'QQQ'
  aiDiagnosisBtn.disabled = true
  aiStatusEl.textContent = 'Generando diagnóstico…'
  aiStatusEl.className = 'ai-status'

  try {
    const result = await postAiDiagnosis(symbol, aiTipoSelect.value)
    aiResultEl.innerHTML = marked.parse(result.text)
    if (result.source === 'local') {
      aiStatusEl.textContent = '⚠ IA no disponible ahora mismo — diagnóstico local por plantilla'
      aiStatusEl.className = 'ai-status local'
    } else {
      aiStatusEl.textContent = '✓ Generado con IA'
      aiStatusEl.className = 'ai-status'
    }
  } catch (err) {
    aiStatusEl.textContent = err.message || 'Error generando el diagnóstico.'
    aiStatusEl.className = 'ai-status error'
  } finally {
    aiDiagnosisBtn.disabled = false
  }
})

let sessionExpiredHandled = false

// Cualquier llamada a la API que reciba 401 (ver api/http.js) dispara
// esto -- una sola vez por expiración, ya que varias llamadas en vuelo
// al momento de expirar podrían disparar el evento varias veces.
window.addEventListener('session-expired', () => {
  if (sessionExpiredHandled) return
  sessionExpiredHandled = true
  showLogin()
  loginError.textContent = 'Tu sesión expiró -- inicia sesión de nuevo.'
  loginError.hidden = false
})

async function init() {
  const session = await me()
  if (session) {
    showDashboard(session.username)
  } else {
    showLogin()
  }
}

init()
