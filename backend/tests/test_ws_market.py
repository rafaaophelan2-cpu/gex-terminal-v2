from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.ws_market import ConnectionState
from app.core.security import create_access_token
from app.main import app


class _FakeFeedForWindow:
    """Doble mínimo de SymbolFeed -- strike_window() solo usa
    spot_price y nearest_dte_strikes(), no hace falta un SymbolFeed real
    (que pegaría a Schwab) para probar la lógica de la ventana."""

    def __init__(self, spot_price: float, strikes: list[float]):
        self.spot_price = spot_price
        self._strikes = strikes

    def nearest_dte_strikes(self) -> list[float]:
        return self._strikes


def test_strike_window_none_without_active_feed():
    state = ConnectionState()
    assert state.strike_window() == (None, None)


def test_strike_window_uses_strike_rank_not_dollar_distance_qqq():
    # QQQ: strikes de 1 USD cerca del ATM -- strike_range=5 debe dar una
    # ventana de +-5 USD aprox (5 strikes reales arriba/abajo).
    strikes = [710.0 + i for i in range(21)]  # 710..730
    state = ConnectionState()
    state.strike_range = 5
    state.feed = _FakeFeedForWindow(spot_price=720.0, strikes=strikes)
    min_s, max_s = state.strike_window()
    assert min_s == 716.0  # 5to strike hacia abajo desde 720 (720,719,...,716)
    assert max_s == 725.0  # 5to strike hacia arriba desde 720 (721,...,725)


def test_strike_window_scales_correctly_for_wide_strike_increments_ndx():
    # NDX: strikes de 100 USD -- el bug real era usar spot +- strike_range
    # en DÓLARES acá, lo que con strike_range=25 (pensado como "25
    # strikes", no "25 dólares") dejaba la ventana casi vacía en un
    # subyacente de ~29000. Con la ventana por RANGO, strike_range=3 da
    # 3 strikes reales arriba/abajo sin importar que estén a 100 USD de
    # distancia entre sí.
    strikes = [29000.0, 29100.0, 29200.0, 29300.0, 29400.0, 29500.0, 29600.0, 29700.0]
    state = ConnectionState()
    state.strike_range = 3
    state.feed = _FakeFeedForWindow(spot_price=29368.44, strikes=strikes)
    min_s, max_s = state.strike_window()
    assert min_s == 29100.0  # 3er strike hacia abajo desde el ATM
    assert max_s == 29600.0  # 3er strike hacia arriba desde el ATM


def test_strike_window_scales_correctly_for_fractional_increments_vix():
    # VIX: strikes de 0.5 USD -- strike_range=4 debe dar solo +-2 USD de
    # ventana real, no +-4 USD como con el cálculo viejo en dólares.
    strikes = [12.0 + i * 0.5 for i in range(20)]  # 12.0..21.5
    state = ConnectionState()
    state.strike_range = 4
    state.feed = _FakeFeedForWindow(spot_price=15.84, strikes=strikes)
    min_s, max_s = state.strike_window()
    assert min_s == 14.0
    assert max_s == 17.5


def test_strike_window_falls_back_to_dollar_range_when_no_strikes_yet():
    # Feed recién suscripto, todavía sin tick -- no hay strikes reales
    # para calcular por rango, se usa el fallback en dólares (peor que
    # nada, pero evita romper antes del primer tick).
    state = ConnectionState()
    state.strike_range = 10
    state.feed = _FakeFeedForWindow(spot_price=500.0, strikes=[])
    min_s, max_s = state.strike_window()
    assert min_s == 490.0
    assert max_s == 510.0


def test_ws_market_rejects_connection_without_token():
    # El accept() va ANTES de validar el token (ver comentario en
    # ws_market.py): un navegador real solo puede leer el código de
    # cierre real (4401, no un genérico 1006) si la conexión se aceptó
    # primero -- así que acá el close llega DESPUÉS de entrar al 'with',
    # recién al intentar recibir algo.
    client = TestClient(app, base_url="https://testserver")
    with client.websocket_connect("/ws/market") as ws:
        try:
            ws.receive_json()
            assert False, "se esperaba que el servidor cerrara la conexión sin token"
        except WebSocketDisconnect as exc:
            assert exc.code == 4401


def test_ws_market_rejects_connection_with_invalid_token():
    client = TestClient(app, base_url="https://testserver")
    with client.websocket_connect("/ws/market?token=not-a-real-token") as ws:
        try:
            ws.receive_json()
            assert False, "se esperaba que el servidor cerrara la conexión con token inválido"
        except WebSocketDisconnect as exc:
            assert exc.code == 4401


def test_ws_market_accepts_connection_with_valid_token():
    token = create_access_token(subject="trader1")
    client = TestClient(app, base_url="https://testserver")
    # Con token válido el servidor acepta el handshake -- no se prueba
    # más allá de eso acá (el tick loop pega a Schwab de verdad, ya
    # verificado en vivo por separado); solo que la puerta de auth deja
    # pasar un token bueno en vez de cerrar con 4401.
    with client.websocket_connect(f"/ws/market?token={token}") as ws:
        ws.close()
