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
# SPX/QQQ de forma directa, y solo agregarían ruido al prompt de la IA.
RELEVANT_COUNTRY = "US"
# Los 3 niveles de Finnhub, SIN excluir 'low' -- pedido explícito: se
# muestran los 3 con un símbolo de color propio en vez de descartar el
# de menor impacto (ver domain/news_filter... no, ver frontend/newsPanel.js
# para el mapeo de color -- acá solo se decide QUÉ nivel de impacto entra).
RELEVANT_IMPACT = {"low", "medium", "high"}

_cache: dict[str, tuple[float, list[dict]]] = {}


def _relevant_week_range(today):
    """Lunes-domingo de la semana relevante -- pedido explícito del
    usuario: en fin de semana (sábado/domingo) no tiene sentido mostrar
    una semana que ya terminó, así que se muestra la semana SIGUIENTE; en
    día hábil se muestra la semana ACTUAL completa (lunes a domingo,
    incluye los días que ya pasaron -- útil para revisar qué ya salió
    antes de ver qué falta, igual que cualquier calendario económico
    normal)."""
    monday = today - timedelta(days=today.weekday())
    if today.weekday() >= 5:  # sábado=5, domingo=6 (Monday=0 en Python)
        monday += timedelta(days=7)
    return monday, monday + timedelta(days=6)


async def fetch_economic_calendar() -> list[dict]:
    """Eventos macro de EE.UU. de la semana relevante (ver
    _relevant_week_range -- semana actual en día hábil, semana siguiente
    en fin de semana), hora de Nueva York. Usado tanto por GET
    /market/economic-calendar (pestaña News) como por el prompt de la IA
    (ver services/ai_context.py) -- mismo calendario para ambos, así el
    bot puede razonar sobre catalizadores de DÍAS por delante (no solo
    los de hoy), igual que un analista de order flow real.

    None/[] si no hay API key configurada o el fetch falla -- opcional
    igual que MarketData.app (ver marketdata_client.py): nunca debe
    bloquear el resto del diagnóstico de la IA.

    Cada item: {"date": "2026-09-14", "time": "08:30" (hora NY o "" si es
    todo el día), "event": str, "impact": "low"|"medium"|"high",
    "actual": str|None, "forecast": str|None, "previous": str|None}."""
    settings = get_settings()
    if not settings.finnhub_api_key:
        return []

    today = datetime.now(NY_TZ).date()
    week_start, week_end = _relevant_week_range(today)
    cache_key = f"week:{week_start.isoformat()}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                CALENDAR_URL,
                params={
                    "token": settings.finnhub_api_key,
                    "from": week_start.isoformat(),
                    "to": (week_end + timedelta(days=1)).isoformat(),
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

    week_start_str = week_start.isoformat()
    week_end_str = week_end.isoformat()
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
        # se descarta cualquier evento fuera de [week_start, week_end] (el
        # rango from/to de arriba puede traer alguno de un día extra por
        # huso horario).
        raw_time = str(item.get("time") or "")
        if " " not in raw_time:
            continue
        date_part, time_part = raw_time.split(" ", 1)
        if not (week_start_str <= date_part <= week_end_str):
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
    # Cachea por semana -- no vale la pena golpear la API de nuevo por
    # cada pedido dentro de la misma semana (mismo espíritu de cuidado de
    # cuota que MarketData.app); el 'actual' de un evento recién publicado
    # puede tardar hasta este TTL en reflejarse, aceptable para este uso.
    _cache[cache_key] = (0.0, events)
    if len(_cache) > 4:
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
