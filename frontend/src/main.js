import './style.css'
import { login, logout, me } from './api/auth.js'
import { MarketWebSocketClient } from './api/ws.js'
import { renderChainFull, resetGexInfoChart, updateTick } from './charts/gexInfoChart.js'
import { renderGreeksChart, resetGreeksChart } from './charts/greeksChart.js'

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

function isGreeksTabActive() {
  return document.getElementById('tab-greeks').classList.contains('active')
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
  await logout()
  showLogin()
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
