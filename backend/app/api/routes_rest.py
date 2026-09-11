import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import require_auth
from app.domain.ai_fallback import generate_local_diagnosis
from app.domain.ai_prompt import build_default_user_prompt, build_intraday_context, build_system_prompt
from app.domain.drift import compute_drift_series
from app.domain.heatmap import compute_heatmap_matrix
from app.domain.metrics import compute_metrics_for_dte
from app.integrations.groq_client import query_groq
from app.integrations.schwab_client import fetch_price_history, fetch_vix
from app.integrations.supabase_client import fetch_available_dates, fetch_gex_history
from app.models.schemas import AiDiagnosisRequest, AiDiagnosisResponse
from app.services.market_feed import feed_registry

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
    feed = feed_registry.get(body.symbol)
    if feed is None or feed.df.empty or feed.spot_price <= 0:
        raise HTTPException(
            status_code=409,
            detail=f"No hay datos en vivo para {body.symbol} todavía -- abre GEX INFO en ese símbolo primero.",
        )

    exp_keys = [feed.nearest_exp_key] if feed.nearest_exp_key else []
    metrics = compute_metrics_for_dte(feed.df, exp_keys, feed.spot_price)

    today = datetime.now(NY_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    candles, vix_val = await asyncio.gather(
        fetch_price_history(body.symbol, today),
        fetch_vix(),
    )
    intraday_context = build_intraday_context(candles, feed.spot_price)

    system_prompt = build_system_prompt(
        ticker=body.symbol,
        spot=feed.spot_price,
        metrics=metrics,
        vix_val=vix_val,
        intraday_context=intraday_context,
        conversion_ratio=NQ_QQQ_RATIO,
    )
    user_prompt = build_default_user_prompt(body.tipo_analisis)

    ai_text = await query_groq(system_prompt, user_prompt)
    if ai_text:
        return AiDiagnosisResponse(text=ai_text, source="groq")

    local_text = generate_local_diagnosis(body.symbol, feed.spot_price, metrics, vix_val, NQ_QQQ_RATIO)
    return AiDiagnosisResponse(text=local_text, source="local")
