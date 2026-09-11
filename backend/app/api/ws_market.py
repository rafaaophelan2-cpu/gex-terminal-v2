import asyncio
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/diag")
async def websocket_diagnostic(websocket: WebSocket):
    """Endpoint mínimo para verificar en producción que el host (Back4app)
    sostiene una conexión WebSocket real: manda un tick con contador cada
    segundo y responde a 'ping' con 'pong'. Se usa solo para el gate de
    Fase 1 ("¿Back4app soporta WS de verdad?") antes de construir
    ws_market.py completo (subscribe/change_dte/tick real) sobre este host."""
    await websocket.accept()
    try:
        send_task = asyncio.create_task(_send_ticks(websocket))
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_json({"type": "pong", "ts": time.time()})
    except WebSocketDisconnect:
        pass
    finally:
        send_task.cancel()


async def _send_ticks(websocket: WebSocket):
    counter = 0
    while True:
        await websocket.send_json({"type": "tick", "counter": counter, "ts": time.time()})
        counter += 1
        await asyncio.sleep(1)
