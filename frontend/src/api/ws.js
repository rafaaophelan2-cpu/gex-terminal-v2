import { WS_BASE } from '../config.js'
import { getToken } from './http.js'

// El backend cierra el handshake con este código cuando no hay token
// válido (ver ws_market.py) -- ante esto no tiene sentido reintentar
// reconectar en loop, hay que mandar al usuario de vuelta al login.
const WS_AUTH_FAILED_CODE = 4401

const HEARTBEAT_INTERVAL_MS = 20000
const RECONNECT_MIN_MS = 500
const RECONNECT_MAX_MS = 10000

/**
 * Cliente WebSocket con reconexión (backoff exponencial), heartbeat
 * ping/pong, y re-subscribe automático al reconectar -- port del diseño
 * de WebSocketClient descrito en el plan.
 */
export class MarketWebSocketClient {
  constructor({ onMessage, onStatusChange } = {}) {
    this.onMessage = onMessage || (() => {})
    this.onStatusChange = onStatusChange || (() => {})
    this.ws = null
    this.heartbeatTimer = null
    this.reconnectDelay = RECONNECT_MIN_MS
    this.lastSubscribe = { type: 'subscribe', symbol: 'QQQ', strike_range: 25 }
    this._manualClose = false
  }

  connect() {
    this._manualClose = false
    this._setStatus('connecting')

    // El WebSocket nativo del navegador no permite mandar headers custom
    // (Authorization) en el handshake -- a diferencia de las llamadas
    // REST, acá el token viaja como query param.
    const token = getToken()
    const url = `${WS_BASE}/ws/market${token ? `?token=${encodeURIComponent(token)}` : ''}`
    this.ws = new WebSocket(url)

    this.ws.onopen = () => {
      this.reconnectDelay = RECONNECT_MIN_MS
      this._setStatus('connected')
      this.send(this.lastSubscribe)
      this._startHeartbeat()
    }

    this.ws.onmessage = (event) => {
      let data
      try {
        data = JSON.parse(event.data)
      } catch {
        return
      }
      this.onMessage(data)
    }

    this.ws.onclose = (event) => {
      this._stopHeartbeat()
      this._setStatus('disconnected')
      if (event.code === WS_AUTH_FAILED_CODE) {
        this._manualClose = true
        window.dispatchEvent(new CustomEvent('session-expired'))
        return
      }
      if (!this._manualClose) this._scheduleReconnect()
    }

    this.ws.onerror = () => {
      this.ws?.close()
    }
  }

  send(msg) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
    }
  }

  subscribe(symbol, strikeRange) {
    this.lastSubscribe = { type: 'subscribe', symbol, strike_range: strikeRange }
    this.send(this.lastSubscribe)
  }

  changeStrikeRange(strikeRange) {
    this.lastSubscribe = { ...this.lastSubscribe, strike_range: strikeRange }
    this.send({ type: 'change_strike_range', strike_range: strikeRange })
  }

  close() {
    this._manualClose = true
    this._stopHeartbeat()
    this.ws?.close()
  }

  _startHeartbeat() {
    this._stopHeartbeat()
    this.heartbeatTimer = setInterval(() => this.send({ type: 'ping' }), HEARTBEAT_INTERVAL_MS)
  }

  _stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  _scheduleReconnect() {
    this._setStatus('reconnecting')
    setTimeout(() => {
      if (!this._manualClose) this.connect()
    }, this.reconnectDelay)
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, RECONNECT_MAX_MS)
  }

  _setStatus(status) {
    this.onStatusChange(status)
  }
}
