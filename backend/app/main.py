import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_auth import router as auth_router
from app.api.routes_chat import router as chat_router
from app.api.routes_rest import router as rest_router
from app.api.ws_market import router as ws_router
from app.config import get_settings
from app.services.iv_percentile_updater import iv_percentile_updater_loop
from app.services.quantower_pusher import quantower_pusher_loop
from app.services.snapshot_writer import snapshot_writer_loop

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ambos tasks corren siempre (con o sin conexiones WS activas) --
    # dentro solo actúan sobre símbolos con al menos un subscriptor, así
    # que en la práctica no hacen nada hasta que alguien se conecta, pero
    # no dependen de ninguna conexión en particular.
    snapshot_task = asyncio.create_task(snapshot_writer_loop())
    quantower_task = asyncio.create_task(quantower_pusher_loop())
    iv_percentile_task = asyncio.create_task(iv_percentile_updater_loop())
    yield
    snapshot_task.cancel()
    quantower_task.cancel()
    iv_percentile_task.cancel()


app = FastAPI(title="GEX Terminal API", lifespan=lifespan)

# CORS: localhost para desarrollo + el dominio de Cloudflare Pages ya
# desplegado (gex-terminal-8vb.pages.dev). allow_origin_regex además
# cubre los deploys de preview de Cloudflare Pages (cada deploy nuevo
# tiene un subdominio con hash distinto bajo el mismo proyecto, ej.
# a56d6d69.gex-terminal-8vb.pages.dev) sin tener que listarlos a mano.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://gex-terminal-8vb.pages.dev"],
    allow_origin_regex=r"https://[a-z0-9-]+\.gex-terminal-8vb\.pages\.dev",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(ws_router)
app.include_router(auth_router)
app.include_router(rest_router)
app.include_router(chat_router)


@app.get("/health")
async def health():
    """Usado por el health check del servicio en Render y por las
    pruebas que confirman que el host no duerme/se pausa inesperadamente."""
    return {"status": "ok", "environment": settings.environment}
