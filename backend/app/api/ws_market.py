import asyncio
import time

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.security import decode_access_token
from app.services.market_feed import SymbolFeed, feed_registry

router = APIRouter()


@router.websocket("/ws/diag")
async def websocket_diagnostic(websocket: WebSocket):
    """Endpoint mínimo sin dependencia de Schwab/mercado, para chequear
    rápido si el host sigue sosteniendo WebSocket (ya verificado en
    ya verificado con Back4app: 90s sostenidos sin cortes -- pendiente
    reverificar en Render, que es el host final, ver plan)."""
    await websocket.accept()
    send_task = None
    try:
        send_task = asyncio.create_task(_send_diag_ticks(websocket))
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_json({"type": "pong", "ts": time.time()})
    except WebSocketDisconnect:
        pass
    finally:
        if send_task:
            send_task.cancel()


async def _send_diag_ticks(websocket: WebSocket):
    counter = 0
    while True:
        await websocket.send_json({"type": "tick", "counter": counter, "ts": time.time()})
        counter += 1
        await asyncio.sleep(1)


DEFAULT_SYMBOL = "QQQ"
DEFAULT_STRIKE_RANGE = 20
POLL_INTERVAL_SECONDS = 0.5


class ConnectionState:
    """Estado LOCAL a esta conexión WS -- nunca una variable de módulo.
    Es la lección central del bug multiusuario ya corregido en la versión
    Streamlit: cada conexión tiene su propio symbol/strike_range, y el
    dato pesado compartido vive en SymbolFeed, no acá."""

    def __init__(self):
        self.symbol: str = DEFAULT_SYMBOL
        self.strike_range: int = DEFAULT_STRIKE_RANGE
        self.feed: SymbolFeed | None = None
        self._last_sent_update: float = 0.0

    async def subscribe(self, symbol: str, strike_range: int) -> None:
        if self.feed is not None:
            await feed_registry.unsubscribe(self.symbol)
        self.symbol = symbol
        self.strike_range = strike_range
        self.feed = await feed_registry.subscribe(symbol, strike_range)
        self._last_sent_update = 0.0  # fuerza a mandar chain_full en el próximo tick

    async def unsubscribe(self) -> None:
        if self.feed is not None:
            await feed_registry.unsubscribe(self.symbol)
            self.feed = None

    def strike_window(self) -> tuple[float, float] | tuple[None, None]:
        if self.feed is None or self.feed.spot_price <= 0:
            return None, None
        return self.feed.spot_price - self.strike_range, self.feed.spot_price + self.strike_range


@router.websocket("/ws/market")
async def websocket_market(websocket: WebSocket, token: str | None = Query(default=None)):
    """Requiere ?token=<JWT> en la URL -- el WebSocket nativo del
    navegador no permite mandar headers custom (Authorization) en el
    handshake, así que el token viaja por query param acá, a diferencia
    de las llamadas REST que sí usan el header. Antes este endpoint no
    validaba nada: cualquiera con la URL podía suscribirse al feed en
    vivo sin haber iniciado sesión.

    El accept() va ANTES de validar el token a propósito: cerrar la
    conexión sin haber aceptado el handshake hace que un navegador real
    solo vea un rechazo HTTP genérico (código 1006, sin acceso al motivo
    ni al código real por seguridad del propio navegador) -- el frontend
    necesita poder leer el código 4401 en el evento onclose para decidir
    "no reintentes conectar, mandá al usuario al login" en vez de
    quedarse reconectando en loop indefinidamente con un token inválido."""
    await websocket.accept()
    username = decode_access_token(token) if token else None
    if not username:
        await websocket.close(code=4401, reason="No autenticado.")
        return

    state = ConnectionState()

    try:
        await state.subscribe(DEFAULT_SYMBOL, DEFAULT_STRIKE_RANGE)
        sender_task = asyncio.create_task(_tick_sender(websocket, state))
        try:
            while True:
                msg = await websocket.receive_json()
                await _handle_client_message(websocket, state, msg)
        finally:
            sender_task.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        await state.unsubscribe()


async def _handle_client_message(websocket: WebSocket, state: ConnectionState, msg: dict) -> None:
    msg_type = msg.get("type")

    if msg_type == "ping":
        await websocket.send_json({"type": "pong", "ts": time.time()})

    elif msg_type in ("subscribe", "change_symbol"):
        symbol = str(msg.get("symbol", state.symbol)).upper().strip() or state.symbol
        strike_range = int(msg.get("strike_range", state.strike_range) or state.strike_range)
        await state.subscribe(symbol, strike_range)

    elif msg_type == "change_strike_range":
        strike_range = int(msg.get("strike_range", state.strike_range))
        await state.subscribe(state.symbol, strike_range)


async def _tick_sender(websocket: WebSocket, state: ConnectionState) -> None:
    """Manda 'chain_full' la primera vez (o tras un cambio de símbolo/
    strike_range) y 'tick' en las actualizaciones siguientes -- el
    frontend decide entre Plotly.react (chain_full) o restyle (tick) según
    el 'type' del mensaje."""
    while True:
        feed = state.feed
        if feed is not None and feed.last_update > state._last_sent_update:
            is_first_send = state._last_sent_update == 0.0
            min_strike, max_strike = state.strike_window()

            await websocket.send_json({
                "type": "chain_full" if is_first_send else "tick",
                "symbol": feed.symbol,
                "ts": feed.last_update,
                "spot": feed.spot_price,
                "schwab_online": feed.schwab_online,
                "gex_info": feed.gex_info_payload(min_strike, max_strike),
                "greeks": feed.greeks_payload(min_strike, max_strike),
                "signals": feed.signals_payload(),
            })
            state._last_sent_update = feed.last_update

        await asyncio.sleep(POLL_INTERVAL_SECONDS)
