import { WS_BASE } from '../config.js'

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
    this.lastSubscribe = { type: 'subscribe', symbol: 'QQQ', strike_range: 20 }
    this._manualClose = false
  }

  connect() {
    this._manualClose = false
    this._setStatus('connecting')

    const url = `${WS_BASE}/ws/market`
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

    this.ws.onclose = () => {
      this._stopHeartbeat()
      this._setStatus('disconnected')
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
