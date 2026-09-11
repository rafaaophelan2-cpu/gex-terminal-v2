import './style.css'
import { login, logout, me } from './api/auth.js'
import { fetchAvailableDates, fetchCandles, fetchDrift, fetchHeatmap } from './api/rest.js'
import { MarketWebSocketClient } from './api/ws.js'
import { renderBackgammaSpotChart, renderBackgammaStrikeChart } from './charts/backgammaChart.js'
import { renderChainFull, resetGexInfoChart, updateTick } from './charts/gexInfoChart.js'
import { renderGreeksChart, resetGreeksChart } from './charts/greeksChart.js'
import { renderLiveGammaChart } from './charts/liveGammaChart.js'
import { renderNetDriftChart } from './charts/netDriftChart.js'

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
  cw1: document.getElementById('metric-cw1'),
  pw1: document.getElementById('metric-pw1'),
  zg: document.getElementById('metric-zg'),
}

let wsClient = null
let activeGreek = 'dex'
let latestGreeksPayload = null
let latestWalls = null
let driftRefreshTimer = null
let liveGammaRefreshTimer = null
let backgammaHeatmap = null
let backgammaPlayTimer = null

const DRIFT_REFRESH_MS = 30000
const LIVE_GAMMA_REFRESH_MS = 30000

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

function startDriftRefresh() {
  stopDriftRefresh()
  loadNetDrift()
  driftRefreshTimer = setInterval(loadNetDrift, DRIFT_REFRESH_MS)
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
    const date = driftDateInput.value || todayInLima()
    const [heatmap, candles] = await Promise.all([
      fetchHeatmap(symbol, date),
      fetchCandles(symbol, date).catch(() => []),
    ])
    renderLiveGammaChart(liveGammaChartEl, heatmap, latestWalls, candles)
  } catch (err) {
    console.error('Error cargando LIVE GAMMA:', err)
  }
}

function startLiveGammaRefresh() {
  stopLiveGammaRefresh()
  loadLiveGamma()
  liveGammaRefreshTimer = setInterval(loadLiveGamma, LIVE_GAMMA_REFRESH_MS)
}

function stopLiveGammaRefresh() {
  if (liveGammaRefreshTimer) {
    clearInterval(liveGammaRefreshTimer)
    liveGammaRefreshTimer = null
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

function fmtMoney(val) {
  if (val === null || val === undefined || Number.isNaN(val)) return '--'
  const abs = Math.abs(val)
  const sign = val >= 0 ? '+' : ''
  if (abs >= 1e9) return `${sign}$${(val / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${sign}$${(val / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${sign}$${(val / 1e3).toFixed(1)}K`
  return `${sign}$${val.toFixed(1)}`
}

function showDashboard(username) {
  loginView.hidden = true
  dashboardView.hidden = false
  userBadge.textContent = `👤 ${username}`
  resetGexInfoChart()
  resetGreeksChart()
  if (!driftDateInput.value) driftDateInput.value = todayInLima()
  connectMarketFeed()
}

function showLogin() {
  loginView.hidden = false
  dashboardView.hidden = true
  wsClient?.close()
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

function handleMarketMessage(data) {
  if (data.type === 'pong') return

  if (data.type === 'chain_full' || data.type === 'tick') {
    metricEls.symbol.textContent = data.symbol
    setMetric(metricEls.spot, data.spot ? `$${data.spot.toFixed(2)}` : '--', 'val-spot')
    const info = data.gex_info
    latestWalls = info.walls
    setMetric(metricEls.netGex, fmtMoney(info.net_gex_total), info.net_gex_total >= 0 ? 'val-positive' : 'val-negative')
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
  stopDriftRefresh()
  stopLiveGammaRefresh()
  stopBackgammaPlay()
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
  if (driftRefreshTimer) loadNetDrift()
  if (liveGammaRefreshTimer) loadLiveGamma()
})

applySymbolBtn.addEventListener('click', () => {
  const symbol = symbolInput.value.trim().toUpperCase() || 'QQQ'
  const strikeRange = Math.min(Math.max(parseInt(strikeRangeInput.value, 10) || 20, 5), 80)
  symbolInput.value = symbol
  strikeRangeInput.value = strikeRange
  resetGexInfoChart()
  wsClient?.subscribe(symbol, strikeRange)
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
  })
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

async function init() {
  const session = await me()
  if (session) {
    showDashboard(session.username)
  } else {
    showLogin()
  }
}

init()
