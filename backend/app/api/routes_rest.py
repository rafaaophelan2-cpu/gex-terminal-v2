from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import require_auth
from app.domain.ai_fallback import generate_local_diagnosis
from app.domain.ai_prompt import build_default_user_prompt, build_system_prompt, classify_vix
from app.domain.drift import compute_drift_series
from app.domain.gamma_grid import compute_gamma_grid, list_expirations
from app.domain.heatmap import compute_heatmap_matrix
from app.domain.vol_surface import compute_vol_surface
from app.integrations.groq_client import query_groq
from app.integrations.schwab_client import fetch_price_history, fetch_vix
from app.integrations.supabase_client import fetch_available_dates, fetch_gex_history
from app.models.schemas import AiDiagnosisRequest, AiDiagnosisResponse
from app.services.ai_context import NoActiveFeedError, build_ai_context
from app.services.market_feed import feed_registry

# Cuántas expiraciones (de la más cercana en adelante) se preseleccionan
# en el GRID cuando el usuario no eligió ninguna DTE todavía.
DEFAULT_GRID_EXPIRATION_COUNT = 6

# 3D SURFACE / 3D VOL SURFACE parten de más expiraciones por defecto que
# el GRID: una tabla con 10+ columnas es ilegible, pero una malla 3D
# necesita más puntos en el eje DTE para verse como una superficie
# continua en vez de un par de cortes aislados.
DEFAULT_SURFACE_EXPIRATION_COUNT = 10

router = APIRouter(prefix="/market", tags=["market"])

# Los snapshots se guardan con 'time' en hora de Nueva York (STORAGE_TZ,
# ver snapshot_writer.py) -- el día calendario de mercado se define en esa
# misma zona, no en la del usuario que pide el endpoint.
NY_TZ = ZoneInfo("America/New_York")

# Mismo factor usado hoy en app.py para traducir niveles de QQQ/SPY a
# puntos de NQ/MNQ en el prompt de la IA -- no varía intradía.
NQ_QQQ_RATIO = 41.125


def _parse_day(date: str | None) -> datetime:
    if date:
        try:
            return datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=NY_TZ)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de fecha inválido, usar YYYY-MM-DD.")
    return datetime.now(NY_TZ).replace(hour=0, minute=0, second=0, microsecond=0)


async def _fetch_day_snapshots(symbol: str, date: str | None) -> list[dict]:
    day_start = _parse_day(date)
    day_end = day_start + timedelta(days=1)

    return await fetch_gex_history(
        symbol,
        start_utc=day_start.isoformat(),
        end_utc=day_end.isoformat(),
        limit=1000,
    )


@router.get("/drift")
async def get_drift(symbol: str = "QQQ", date: str | None = None, _username: str = Depends(require_auth)):
    """Serie de NET DRIFT (horario de mercado, 09:30-16:00 NY) para
    'symbol' en el día calendario 'date' (YYYY-MM-DD, por defecto hoy en
    NY). Es REST (no WebSocket) porque no necesita empujarse en tiempo
    real tick a tick -- el frontend la vuelve a pedir cada tanto."""
    snapshots = await _fetch_day_snapshots(symbol, date)
    return compute_drift_series(snapshots)


@router.get("/heatmap")
async def get_heatmap(symbol: str = "QQQ", date: str | None = None, _username: str = Depends(require_auth)):
    """Matriz strike x tiempo de net_gex real para LIVE GAMMA, construida
    de los mismos snapshots que /drift -- ver domain/heatmap.py. BACKGAMMA
    reusa este mismo endpoint: el scrubber solo necesita, para cada índice
    de tiempo, spot[i] + la columna z[:, i] contra 'strikes'."""
    snapshots = await _fetch_day_snapshots(symbol, date)
    return compute_heatmap_matrix(snapshots)


@router.get("/candles")
async def get_candles(symbol: str = "QQQ", date: str | None = None, _username: str = Depends(require_auth)):
    """Velas reales de 1 minuto (Schwab) para superponer sobre el heatmap
    de LIVE GAMMA -- reemplaza la línea simple de spot por velas
    japonesas de verdad, igual que hacía app.py con fetch_history_schwab."""
    day = _parse_day(date)
    return await fetch_price_history(symbol, day)


@router.get("/vix")
async def get_vix(_username: str = Depends(require_auth)):
    """VIX en vivo + clasificación (mismos cortes que la tarjeta VIX del
    sidebar de app.py, ver domain/ai_prompt.classify_vix) -- REST porque
    no hace falta actualizarlo cada 2s como el tick de WS, el frontend
    lo vuelve a pedir cada cierto intervalo para la barra de métricas."""
    value = await fetch_vix()
    status, description, color = classify_vix(value)
    return {"value": value, "status": status, "description": description, "color": color}


@router.get("/available-dates")
async def get_available_dates(symbol: str = "QQQ", _username: str = Depends(require_auth)):
    """Fechas (NY, más recientes primero) con al menos un snapshot
    guardado -- selector de día de BACKGAMMA."""
    dates = await fetch_available_dates(symbol, NY_TZ)
    return {"dates": dates}


@router.post("/ai-diagnosis", response_model=AiDiagnosisResponse)
async def post_ai_diagnosis(body: AiDiagnosisRequest, _username: str = Depends(require_auth)):
    """Pestaña DATA: diagnóstico bajo demanda (no vive en el tick de WS,
    es caro y no hace falta 1/s). Lee el estado YA calculado por el
    SymbolFeed activo (requiere que alguna conexión WS esté suscrita a
    ese símbolo -- lo normal si el usuario tiene el dashboard abierto en
    ese símbolo, que es el único caso real de uso de este botón).
    Combina eso con velas intradía + VIX en vivo, arma el mismo prompt
    de trading que app.py y llama a Groq; si no hay API key o la llamada
    falla, cae a un diagnóstico local por plantilla en vez de dejar la
    pestaña vacía."""
    try:
        ctx = await build_ai_context(body.symbol)
    except NoActiveFeedError:
        raise HTTPException(
            status_code=409,
            detail=f"No hay datos en vivo para {body.symbol} todavía -- abre GEX INFO en ese símbolo primero.",
        )

    system_prompt = build_system_prompt(
        ticker=body.symbol,
        spot=ctx["spot"],
        metrics=ctx["metrics"],
        vix_val=ctx["vix_val"],
        intraday_context=ctx["intraday_context"],
        conversion_ratio=NQ_QQQ_RATIO,
        overnight_profile=ctx.get("overnight_profile"),
        cash_profile=ctx.get("cash_profile"),
    )
    user_prompt = build_default_user_prompt(body.tipo_analisis)

    ai_text = await query_groq(system_prompt, user_prompt)
    if ai_text:
        return AiDiagnosisResponse(text=ai_text, source="groq")

    local_text = generate_local_diagnosis(body.symbol, ctx["spot"], ctx["metrics"], ctx["vix_val"], NQ_QQQ_RATIO)
    return AiDiagnosisResponse(text=local_text, source="local")


@router.get("/expirations")
async def get_expirations(symbol: str = "QQQ", _username: str = Depends(require_auth)):
    """Expiraciones disponibles (cualquier DTE, no solo la más cercana)
    para el selector de DTEs del GRID -- lee el SymbolFeed activo, igual
    que /ai-diagnosis y el chat (requiere una conexión WS ya suscrita a
    ese símbolo)."""
    feed = feed_registry.get(symbol)
    if feed is None or feed.df.empty:
        return {"expirations": []}
    return {"expirations": list_expirations(feed.df)}


@router.get("/gamma-grid")
async def get_gamma_grid(symbol: str = "QQQ", exp_keys: str = "", _username: str = Depends(require_auth)):
    """GRID: Net GEX real por strike x expiración para las DTE elegidas
    (ver domain/gamma_grid.py) -- 'exp_keys' es una lista separada por
    comas; si viene vacía, se preseleccionan las primeras
    DEFAULT_GRID_EXPIRATION_COUNT expiraciones más cercanas."""
    feed = feed_registry.get(symbol)
    if feed is None or feed.df.empty:
        raise HTTPException(
            status_code=409,
            detail=f"No hay datos en vivo para {symbol} todavía -- abre GEX INFO en ese símbolo primero.",
        )

    selected = [k for k in exp_keys.split(",") if k]
    if not selected:
        all_exps = list_expirations(feed.df)
        selected = [e["exp_key"] for e in all_exps[:DEFAULT_GRID_EXPIRATION_COUNT]]

    return compute_gamma_grid(feed.df, selected)


@router.get("/gamma-surface")
async def get_gamma_surface(symbol: str = "QQQ", exp_keys: str = "", _username: str = Depends(require_auth)):
    """3D SURFACE: mismo Net GEX real por strike x expiración que el GRID
    (ver domain/gamma_grid.py) -- reusa compute_gamma_grid, solo cambia
    cuántas expiraciones se preseleccionan por defecto (más, para una
    malla 3D más completa) sin tocar el default del GRID tabular."""
    feed = feed_registry.get(symbol)
    if feed is None or feed.df.empty:
        raise HTTPException(
            status_code=409,
            detail=f"No hay datos en vivo para {symbol} todavía -- abre GEX INFO en ese símbolo primero.",
        )

    selected = [k for k in exp_keys.split(",") if k]
    if not selected:
        all_exps = list_expirations(feed.df)
        selected = [e["exp_key"] for e in all_exps[:DEFAULT_SURFACE_EXPIRATION_COUNT]]

    return compute_gamma_grid(feed.df, selected)


@router.get("/vol-surface")
async def get_vol_surface(symbol: str = "QQQ", exp_keys: str = "", _username: str = Depends(require_auth)):
    """3D VOL SURFACE: IV% (convención OTM) por strike x expiración -- ver
    domain/vol_surface.py."""
    feed = feed_registry.get(symbol)
    if feed is None or feed.df.empty:
        raise HTTPException(
            status_code=409,
            detail=f"No hay datos en vivo para {symbol} todavía -- abre GEX INFO en ese símbolo primero.",
        )

    selected = [k for k in exp_keys.split(",") if k]
    if not selected:
        all_exps = list_expirations(feed.df)
        selected = [e["exp_key"] for e in all_exps[:DEFAULT_SURFACE_EXPIRATION_COUNT]]

    return compute_vol_surface(feed.df, selected, feed.spot_price)
