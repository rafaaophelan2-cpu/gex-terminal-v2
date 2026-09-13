import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

CALENDAR_URL = "https://finnhub.io/api/v1/calendar/economic"
NEWS_URL = "https://finnhub.io/api/v1/news"

NY_TZ = ZoneInfo("America/New_York")

# TTL del cache de noticias -- a diferencia del calendario económico (que
# solo cambia cuando sale un 'actual' nuevo, ver más abajo), el feed
# general de Finnhub se actualiza seguido durante la sesión. 5 min es
# suficiente para no perderse nada relevante sin pegarle a la API en
# cada carga de la pestaña News (varios usuarios pueden tenerla abierta
# a la vez).
NEWS_CACHE_TTL_SECONDS = 300

# Solo USD -- eventos de otros países (EUR, GBP, etc.) no mueven NQ/MNQ ni
# SPX/QQQ de forma directa, y solo agregarían ruido al prompt de la IA
# (ver Aleks Rosme: "CPI at 8:30 sent tech higher" -- siempre sus propios
# ejemplos son datos de EE.UU.).
RELEVANT_COUNTRY = "US"
# 'low' queda afuera a propósito -- son decenas de datos menores por
# semana (ej. subastas de bonos) que Rosme nunca menciona; solo folder
# naranja/rojo (medium/high) es lo que de verdad mueve el mercado que
# opera este usuario.
RELEVANT_IMPACT = {"medium", "high"}

_cache: dict[str, tuple[float, list[dict]]] = {}


async def fetch_economic_calendar(days_ahead: int = 0) -> list[dict]:
    """Eventos macro de EE.UU. de impacto medio/alto desde HOY hasta
    'days_ahead' días adelante (hora de Nueva York) -- calendario
    económico de Aleks Rosme (CPI/FOMC/NFP con folder rojo/naranja, ver
    ejemplos que pegó el usuario: "CPI at 8:30 sent tech higher"). None/[]
    si no hay API key configurada o el fetch falla -- opcional igual que
    MarketData.app (ver marketdata_client.py): nunca debe bloquear el
    resto del diagnóstico de la IA.

    'days_ahead=0' (default, usado por el prompt de la IA -- "¿qué hay
    HOY?") mantiene el comportamiento de siempre, solo eventos de hoy.
    'days_ahead>0' (usado por GET /market/economic-calendar para la
    pestaña News) suma los días siguientes -- cada item trae su propio
    campo "date" para que el frontend pueda agrupar por día.

    Cada item: {"date": "2026-09-14", "time": "08:30" (hora NY o "" si es
    todo el día), "event": str, "impact": "medium"|"high",
    "actual": str|None, "forecast": str|None, "previous": str|None}."""
    settings = get_settings()
    if not settings.finnhub_api_key:
        return []

    today = datetime.now(NY_TZ).date()
    last_day = today + timedelta(days=days_ahead)
    cache_key = f"{today.isoformat()}:{days_ahead}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                CALENDAR_URL,
                params={
                    "token": settings.finnhub_api_key,
                    "from": today.isoformat(),
                    "to": (last_day + timedelta(days=1)).isoformat(),
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("fetch_economic_calendar() falló -- se omite el calendario esta vez.")
        return []

    raw_events = data.get("economicCalendar") if isinstance(data, dict) else None
    if not isinstance(raw_events, list):
        return []

    today_str = today.isoformat()
    last_day_str = last_day.isoformat()
    events: list[dict] = []
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        if item.get("country") != RELEVANT_COUNTRY:
            continue
        impact = str(item.get("impact") or "").lower()
        if impact not in RELEVANT_IMPACT:
            continue
        # Finnhub trae 'time' como "YYYY-MM-DD HH:MM:SS" en hora de NY --
        # se descarta cualquier evento fuera de [hoy, last_day] (el rango
        # from/to de arriba puede traer alguno de un día extra por huso
        # horario).
        raw_time = str(item.get("time") or "")
        if " " not in raw_time:
            continue
        date_part, time_part = raw_time.split(" ", 1)
        if not (today_str <= date_part <= last_day_str):
            continue

        events.append({
            "date": date_part,
            "time": time_part[:5],
            "event": str(item.get("event") or "Evento económico"),
            "impact": impact,
            "actual": item.get("actual"),
            "forecast": item.get("estimate"),
            "previous": item.get("prev"),
        })

    events.sort(key=lambda e: (e["date"], e["time"]))
    # Cachea por el resto del día -- el calendario de HOY (+ los días
    # siguientes pedidos) no cambia salvo que salga el dato 'actual' de un
    # evento ya pasado, y no vale la pena golpear la API de nuevo por cada
    # pedido (mismo espíritu de cuidado de cuota que MarketData.app).
    _cache[cache_key] = (0.0, events)
    if len(_cache) > 6:
        oldest_key = min(_cache.keys())
        del _cache[oldest_key]
    return events


async def fetch_market_news() -> list[dict]:
    """Feed de noticias de mercado en general (Finnhub, categoría
    'general') -- CRUDO, sin filtrar por relevancia todavía (ver
    domain/news_filter.py::filter_relevant_news, que hace ese trabajo
    para GET /market/news). Finnhub NO da qué ticker impacta cada
    noticia en este endpoint (a diferencia de FinancialJuice, que es
    propietario de ese tageo) -- por eso el filtrado real vive aparte,
    en domain/, como una heurística por palabras clave.

    Cache de NEWS_CACHE_TTL_SECONDS -- []/None si no hay API key o el
    fetch falla, mismo criterio que el resto de este módulo.

    Cada item: {"headline", "summary", "url", "source",
    "datetime" (epoch segundos), "image"}."""
    settings = get_settings()
    if not settings.finnhub_api_key:
        return []

    cache_key = "general"
    cached = _cache.get(cache_key)
    if cached is not None and (time.time() - cached[0]) < NEWS_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                NEWS_URL,
                params={"token": settings.finnhub_api_key, "category": "general"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("fetch_market_news() falló -- se omite el feed esta vez.")
        return cached[1] if cached is not None else []

    if not isinstance(data, list):
        return cached[1] if cached is not None else []

    articles: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        headline = str(item.get("headline") or "").strip()
        if not headline:
            continue
        articles.append({
            "headline": headline,
            "summary": str(item.get("summary") or "").strip(),
            "url": str(item.get("url") or ""),
            "source": str(item.get("source") or ""),
            "datetime": int(item.get("datetime") or 0),
            "image": str(item.get("image") or ""),
        })

    articles.sort(key=lambda a: a["datetime"], reverse=True)
    _cache[cache_key] = (time.time(), articles)
    return articles
