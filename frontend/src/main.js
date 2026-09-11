import './style.css'
import { login, logout, me } from './api/auth.js'
import { MarketWebSocketClient } from './api/ws.js'
import { renderChainFull, resetGexInfoChart, updateTick } from './charts/gexInfoChart.js'

const loginView = document.getElementById('login-view')
const dashboardView = document.getElementById('dashboard-view')
const loginForm = document.getElementById('login-form')
const loginError = document.getElementById('login-error')
const userBadge = document.getElementById('user-badge')
const wsStatusEl = document.getElementById('ws-status')
const logoutBtn = document.getElementById('logout-btn')
const chartEl = document.getElementById('gex-info-chart')

const metricEls = {
  symbol: document.getElementById('metric-symbol'),
  spot: document.getElementById('metric-spot'),
  netGex: document.getElementById('metric-net-gex'),
  cw1: document.getElementById('metric-cw1'),
  pw1: document.getElementById('metric-pw1'),
  zg: document.getElementById('metric-zg'),
}

let wsClient = null

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
  connectMarketFeed()
}

function showLogin() {
  loginView.hidden = false
  dashboardView.hidden = true
  wsClient?.close()
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
    metricEls.spot.textContent = data.spot ? `$${data.spot.toFixed(2)}` : '--'
    const info = data.gex_info
    metricEls.netGex.textContent = fmtMoney(info.net_gex_total)
    metricEls.cw1.textContent = info.walls?.cw1 ? `$${info.walls.cw1.toFixed(0)}` : '--'
    metricEls.pw1.textContent = info.walls?.pw1 ? `$${info.walls.pw1.toFixed(0)}` : '--'
    metricEls.zg.textContent = info.flip_level ? `$${info.flip_level.toFixed(2)}` : '--'

    if (info.by_strike && info.by_strike.length > 0) {
      if (data.type === 'chain_full') {
        renderChainFull(chartEl, info, data.spot)
      } else {
        updateTick(chartEl, info, data.spot)
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

async function init() {
  const session = await me()
  if (session) {
    showDashboard(session.username)
  } else {
    showLogin()
  }
}

init()
