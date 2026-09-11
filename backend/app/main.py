from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_auth import router as auth_router
from app.api.ws_market import router as ws_router
from app.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fase 1+: acá se arrancan como background tasks el FeedManager por
    # símbolo, snapshot_writer (Supabase/Firebase cada 60s) y
    # quantower_pusher (Firebase /live_levels cada 8s) — deben correr
    # SIEMPRE, con o sin conexiones WS activas (ver plan: Quantower depende
    # de /live_levels independientemente de si alguien mira el dashboard).
    yield
    # Fase 1+: cancelar/cerrar limpiamente esas tasks y los clientes HTTP.


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
    """Usado por el health check del servicio en Back4app y por las
    pruebas que confirman que el host no duerme/se pausa inesperadamente."""
    return {"status": "ok", "environment": settings.environment}
