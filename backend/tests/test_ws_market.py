from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.security import create_access_token
from app.main import app


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
