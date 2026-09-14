from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import require_auth
from app.domain.ai_fallback import generate_local_diagnosis
from app.domain.ai_prompt import build_daily_briefing_user_prompt, build_default_user_prompt, build_short_term_user_prompt, build_system_prompt, classify_vix
from app.domain.drift import compute_drift_series
from app.domain.gamma_grid import compute_gamma_grid, list_expirations
from app.domain.heatmap import (
    compute_charm_heatmap_matrix,
    compute_charm_trend_line,
    compute_gamma_trend_lines,
    compute_heatmap_matrix,
)
from app.domain.implied_range import compute_implied_range
from app.domain.metrics import compute_metrics_for_dte
from app.domain.news_filter import filter_relevant_news
from app.domain.vol_surface import compute_vol_surface
from app.integrations.finnhub_client import fetch_market_news
from app.integrations.forexfactory_client import fetch_economic_calendar
from app.integrations.groq_client import query_groq
from app.integrations.marketdata_client import fetch_oi_map
from app.integrations.schwab_client import fetch_price_history, fetch_vix, fetch_vix_term_structure
from app.integrations.supabase_client import fetch_available_dates, fetch_gex_history
from app.models.schemas import AiDiagnosisRequest, AiDiagnosisResponse
from app.services.ai_context import NoActiveFeedError, build_ai_context, dte_from_exp_key
from app.services.cross_check import fetch_ndx_compounded_levels
from app.services.market_feed import MARKETDATA_OI_SYMBOLS, feed_registry
from app.services.tradingview_string_updater import latest_strings as tv_latest_strings

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
async def get_drift(symbol: str = "QQQ", date: str | None = None, otm_only: bool = False, _username: str = Depends(require_auth)):
    """Serie de NET DRIFT (horario de mercado, 09:30-16:00 NY) para
    'symbol' en el día calendario 'date' (YYYY-MM-DD, por defecto hoy en
    NY). Es REST (no WebSocket) porque no necesita empujarse en tiempo
    real tick a tick -- el frontend la vuelve a pedir cada tanto.

    'otm_only': igual que el toggle de Aleks Rosme entre su vista de
    "todas las strikes" y su vista "OTM" -- cuando viene en True, filtra
    cada snapshot a calls con strike>=spot y puts con strike<=spot antes
    de sumar (ver domain/drift.py)."""
    snapshots = await _fetch_day_snapshots(symbol, date)
    return compute_drift_series(snapshots, otm_only=otm_only)


@router.get("/heatmap")
async def get_heatmap(symbol: str = "QQQ", date: str | None = None, _username: str = Depends(require_auth)):
    """Matriz strike x tiempo de net_gex real para LIVE GAMMA, construida
    de los mismos snapshots que /drift -- ver domain/heatmap.py. BACKGAMMA
    reusa este mismo endpoint: el scrubber solo necesita, para cada índice
    de tiempo, spot[i] + la columna z[:, i] contra 'strikes'.

    Suma también gamma_peak/gamma_trough/gamma_zero (Call Wall/Put Wall/
    Zero Gamma reales de cada instante, ver
    domain/heatmap.py::compute_gamma_trend_lines) para las líneas de
    tendencia que el frontend superpone al heatmap -- mismo endpoint,
    respuesta extendida, no rompe a quien ya lo consumía."""
    snapshots = await _fetch_day_snapshots(symbol, date)
    matrix = compute_heatmap_matrix(snapshots)
    trend_lines = compute_gamma_trend_lines(snapshots)
    return {**matrix, **trend_lines}


@router.get("/heatmap-charm")
async def get_charm_heatmap(symbol: str = "QQQ", date: str | None = None, _username: str = Depends(require_auth)):
    """Igual que /heatmap pero con Charm Exposure (net_chex) en vez de
    Net GEX -- ver domain/heatmap.py::compute_charm_heatmap_matrix. Mismo
    endpoint de snapshots, mismo formato de respuesta (times/strikes/z/spot),
    para que el frontend reuse el mismo chart de Plotly cambiando solo la
    fuente de datos.

    Suma también charm_zero (ver
    domain/heatmap.py::compute_charm_trend_line) -- la única línea de
    tendencia que Aleks Rosme dibuja sobre este panel."""
    snapshots = await _fetch_day_snapshots(symbol, date)
    matrix = compute_charm_heatmap_matrix(snapshots)
    trend_line = compute_charm_trend_line(snapshots)
    return {**matrix, **trend_line}


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


@router.get("/economic-calendar")
async def get_economic_calendar(_username: str = Depends(require_auth)):
    """Calendario económico de EE.UU. (CPI/FOMC/NFP, los 3 niveles de
    impacto) de la semana relevante -- ver
    integrations/forexfactory_client.py::fetch_economic_calendar (semana
    actual en día hábil, semana siguiente en fin de semana). Feed público
    sin API key -- [] solo si el fetch falla."""
    events = await fetch_economic_calendar()
    return {"events": events}


@router.get("/news")
async def get_news(_username: str = Depends(require_auth)):
    """Feed de noticias filtrado a lo que probablemente impacta QQQ/NQ
    (pedido explícito del usuario) -- ver domain/news_filter.py para el
    disclaimer de que es una heurística por palabras clave, no un
    clasificador real (Finnhub no tagea sus noticias por ticker). Los
    ~40 más recientes alcanzan de sobra para una sesión de trading."""
    articles = filter_relevant_news(await fetch_market_news())
    return {"articles": articles[:40]}


@router.get("/available-dates")
async def get_available_dates(symbol: str = "QQQ", _username: str = Depends(require_auth)):
    """Fechas (NY, más recientes primero) con al menos un snapshot
    guardado -- selector de día de BACKGAMMA."""
    dates = await fetch_available_dates(symbol, NY_TZ)
    return {"dates": dates}


@router.get("/tradingview-string")
async def get_tradingview_string(symbol: str = "QQQ", _username: str = Depends(require_auth)):
    """String de niveles para el indicador de Pine Script "Gamma Levels
    para TradingView" (ver sección Utilidad del frontend) -- lo genera
    tradingview_string_updater_loop una vez por minuto durante la Cash
    Session (08:31-15:00 hora Lima). 'string' viene None si todavía no se
    generó ninguno hoy (antes de las 08:31, o sin feed activo para el
    símbolo)."""
    entry = tv_latest_strings.get(symbol)
    if entry is None:
        return {"symbol": symbol, "string": None, "updated_at": None}
    return entry


@router.get("/vix-term-structure")
async def get_vix_term_structure(_username: str = Depends(require_auth)):
    """VIX (30d) vs VIX3M (90d) -- contango/backwardation, ver
    fetch_vix_term_structure en schwab_client.py. Global, no depende de
    ningún símbolo/feed activo."""
    result = await fetch_vix_term_structure()
    if not result:
        return {"vix": None, "vix3m": None, "state": "n/a"}
    return result


@router.get("/implied-range")
async def get_implied_range(symbol: str = "QQQ", _username: str = Depends(require_auth)):
    """Banda de movimiento esperado (expected move) desde la IV ATM de la
    expiración más cercana del feed YA activo -- ver domain/implied_range.py.
    No pide ningún dato nuevo a Schwab, deriva todo de feed.df."""
    feed = feed_registry.get(symbol)
    if feed is None or feed.df.empty or feed.spot_price <= 0:
        return {"expected_move": None, "one_sd": None, "two_sd": None}

    exp_keys = [feed.nearest_exp_key] if feed.nearest_exp_key else []
    metrics = compute_metrics_for_dte(feed.df, exp_keys, feed.spot_price)
    return compute_implied_range(feed.spot_price, metrics.get("atm_iv", 0.20), dte_from_exp_key(feed.nearest_exp_key))


@router.get("/compounded-levels")
async def get_compounded_levels(symbol: str = "QQQ", _username: str = Depends(require_auth)):
    """Niveles "compuestos" -- cruce en vivo contra la cadena de NDX (ver
    services/cross_check.py). Solo aplica para QQQ/SPY (ambos sobre
    Nasdaq-100, el mismo mercado que NDX); para cualquier otro símbolo
    devuelve matches=[] sin pedir nada a Schwab."""
    feed = feed_registry.get(symbol)
    if feed is None or feed.df.empty or feed.spot_price <= 0:
        return {"ratio": None, "ndx_spot": None, "matches": []}

    exp_keys = [feed.nearest_exp_key] if feed.nearest_exp_key else []
    metrics = compute_metrics_for_dte(feed.df, exp_keys, feed.spot_price)
    result = await fetch_ndx_compounded_levels(symbol, feed.spot_price, metrics)
    if result is None:
        return {"ratio": None, "ndx_spot": None, "matches": []}
    return {
        "ratio": result["ratio"],
        "ndx_spot": result["ndx_spot"],
        "matches": [
            {
                "primary_name": m.primary_name,
                "primary_value": m.primary_value,
                "secondary_name": m.secondary_name,
                "secondary_value_translated": m.secondary_value_translated,
            }
            for m in result["matches"]
        ],
    }


@router.post("/refresh-oi")
async def force_refresh_oi(symbol: str, _username: str = Depends(require_auth)):
    """Fuerza un fetch real de Open Interest a MarketData.app para NDX/VIX,
    saltando el cache normal (15 min a 1h, ver marketdata_client.py) y el
    corte de fin de semana -- pensado como margen manual de emergencia
    (ver oi_scheduler.py para el refresco automático de pre-mercado), NO
    para uso rutinario: cada llamada consume una unidad real del cupo
    diario de la cuenta. Sigue respetando el cooldown de fallos, así que
    un doble click no dispara dos requests seguidos."""
    if symbol not in MARKETDATA_OI_SYMBOLS:
        raise HTTPException(status_code=400, detail=f"'{symbol}' no usa MarketData.app -- solo aplica a {sorted(MARKETDATA_OI_SYMBOLS)}.")
    oi_map = await fetch_oi_map(symbol, force=True)
    return {"ok": oi_map is not None, "strikes": len(oi_map) if oi_map else 0}


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

    # El ratio NQ_QQQ_RATIO fijo puede quedar desactualizado (misma causa
    # raíz que ya se resolvió del lado de Quantower con ManualRatio en
    # GexProfileCloud.cs: Schwab no da una cotización de futuros NQ
    # confiable) -- si el usuario manda uno manual desde la web, tiene
    # prioridad total, igual criterio que en el indicador.
    conversion_ratio = body.conversion_ratio if body.conversion_ratio and body.conversion_ratio > 0 else NQ_QQQ_RATIO

    # Briefings tiene 3 botones: "Análisis para el día" dispara el modo
    # corto/en prosa (ver ESTILO DE BRIEFING DIARIO en ai_prompt.py),
    # "Corto Plazo" dispara el foco en niveles internos (ver ESTILO CORTO
    # PLAZO); cualquier otro valor (incluido "Posibles Escenarios", o un
    # tipo_analisis viejo cacheado en el cliente de alguien) cae al
    # informe completo de siempre -- degrada sin romper. Se calcula ANTES
    # de armar el system_prompt (no después, como antes) porque
    # response_mode ahora también decide qué secciones del prompt se
    # incluyen -- ver build_system_prompt: un botón ya sabe qué formato
    # quiere, así que no hace falta mandarle a Groq las instrucciones de
    # LOS OTROS DOS formatos que este pedido puntual no va a usar nunca.
    if body.tipo_analisis == "Análisis para el día":
        response_mode = "daily_briefing"
        user_prompt = build_daily_briefing_user_prompt()
    elif body.tipo_analisis == "Corto Plazo":
        response_mode = "short_term"
        user_prompt = build_short_term_user_prompt()
    else:
        response_mode = "full"
        user_prompt = build_default_user_prompt(body.tipo_analisis)

    system_prompt = build_system_prompt(
        ticker=body.symbol,
        spot=ctx["spot"],
        metrics=ctx["metrics"],
        vix_val=ctx["vix_val"],
        intraday_context=ctx["intraday_context"],
        conversion_ratio=conversion_ratio,
        overnight_profile=ctx.get("overnight_profile"),
        cash_profile=ctx.get("cash_profile"),
        vix_term_structure=ctx.get("vix_term_structure"),
        ndx_cross_check=ctx.get("ndx_cross_check"),
        implied_range=ctx.get("implied_range"),
        oi_is_volume_proxy=ctx.get("oi_is_volume_proxy", False),
        macro_levels=ctx.get("macro_levels"),
        vix_gamma_levels=ctx.get("vix_gamma_levels"),
        economic_calendar=ctx.get("economic_calendar"),
        response_mode=response_mode,
    )

    ai_text = await query_groq(system_prompt, user_prompt)
    if ai_text:
        return AiDiagnosisResponse(text=ai_text, source="groq")

    local_text = generate_local_diagnosis(body.symbol, ctx["spot"], ctx["metrics"], ctx["vix_val"], conversion_ratio)
    return AiDiagnosisResponse(text=local_text, source="local")


@router.get("/expirations")
async def get_expirations(symbol: str = "QQQ", _username: str = Depends(require_auth)):
    """Expiraciones disponibles (cualquier DTE, no solo la más cercana)
    para el selector de DTEs del GRID -- lee feed.deep_df (la cadena
    ANCHA, ver market_feed.py), no feed.df (angosta, la del tick en vivo
    de GEX INFO/GREEKS), para que las expiraciones lejanas también traigan
    datos reales en vez de aparecer casi vacías."""
    feed = feed_registry.get(symbol)
    if feed is None or feed.deep_df.empty:
        return {"expirations": []}
    return {"expirations": list_expirations(feed.deep_df)}


@router.get("/gamma-grid")
async def get_gamma_grid(symbol: str = "QQQ", exp_keys: str = "", _username: str = Depends(require_auth)):
    """Gamma Heatmap: Net GEX real por strike x expiración para las DTE
    elegidas (ver domain/gamma_grid.py) -- 'exp_keys' es una lista
    separada por comas; si viene vacía, se preseleccionan las primeras
    DEFAULT_GRID_EXPIRATION_COUNT expiraciones más cercanas."""
    feed = feed_registry.get(symbol)
    if feed is None or feed.deep_df.empty:
        raise HTTPException(
            status_code=409,
            detail=f"No hay datos en vivo para {symbol} todavía -- abre GEX INFO en ese símbolo primero.",
        )

    selected = [k for k in exp_keys.split(",") if k]
    if not selected:
        all_exps = list_expirations(feed.deep_df)
        selected = [e["exp_key"] for e in all_exps[:DEFAULT_GRID_EXPIRATION_COUNT]]

    return compute_gamma_grid(feed.deep_df, selected)


@router.get("/gamma-surface")
async def get_gamma_surface(symbol: str = "QQQ", exp_keys: str = "", _username: str = Depends(require_auth)):
    """3D SURFACE: mismo Net GEX real por strike x expiración que el GRID
    (ver domain/gamma_grid.py) -- reusa compute_gamma_grid, solo cambia
    cuántas expiraciones se preseleccionan por defecto (más, para una
    malla 3D más completa) sin tocar el default del GRID tabular."""
    feed = feed_registry.get(symbol)
    if feed is None or feed.deep_df.empty:
        raise HTTPException(
            status_code=409,
            detail=f"No hay datos en vivo para {symbol} todavía -- abre GEX INFO en ese símbolo primero.",
        )

    selected = [k for k in exp_keys.split(",") if k]
    if not selected:
        all_exps = list_expirations(feed.deep_df)
        selected = [e["exp_key"] for e in all_exps[:DEFAULT_SURFACE_EXPIRATION_COUNT]]

    return compute_gamma_grid(feed.deep_df, selected)


@router.get("/vol-surface")
async def get_vol_surface(symbol: str = "QQQ", exp_keys: str = "", _username: str = Depends(require_auth)):
    """3D VOL SURFACE: IV% (convención OTM) por strike x expiración -- ver
    domain/vol_surface.py."""
    feed = feed_registry.get(symbol)
    if feed is None or feed.deep_df.empty:
        raise HTTPException(
            status_code=409,
            detail=f"No hay datos en vivo para {symbol} todavía -- abre GEX INFO en ese símbolo primero.",
        )

    selected = [k for k in exp_keys.split(",") if k]
    if not selected:
        all_exps = list_expirations(feed.deep_df)
        selected = [e["exp_key"] for e in all_exps[:DEFAULT_SURFACE_EXPIRATION_COUNT]]

    return compute_vol_surface(feed.deep_df, selected, feed.spot_price)
