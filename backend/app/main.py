import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_auth import router as auth_router
from app.api.ws_market import router as ws_router
from app.config import get_settings
from app.services.snapshot_writer import snapshot_writer_loop

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # snapshot_writer corre siempre (con o sin conexiones WS activas) --
    # dentro solo actúa sobre símbolos con al menos un subscriptor, así
    # que en la práctica no hace nada hasta que alguien se conecta, pero
    # no depende de ninguna conexión en particular (mismo criterio que
    # quantower_pusher, que se suma en Fase 3 cuando se conecte Firebase).
    snapshot_task = asyncio.create_task(snapshot_writer_loop())
    yield
    snapshot_task.cancel()


app = FastAPI(title="GEX Terminal API", lifespan=lifespan)

# CORS: en Fase 0/1 se deja abierto a localhost para desarrollo. Antes de
# desplegar el frontend en Cloudflare Pages, restringir allow_origins al
# dominio exacto de Pages y activar allow_credentials para que la cookie
# de sesión viaje en el handshake del WebSocket.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(ws_router)
app.include_router(auth_router)


@app.get("/health")
async def health():
    """Usado por el health check del servicio en Render y por las
    pruebas que confirman que el host no duerme/se pausa inesperadamente."""
    return {"status": "ok", "environment": settings.environment}
