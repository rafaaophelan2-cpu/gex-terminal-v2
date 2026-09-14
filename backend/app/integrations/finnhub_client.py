import logging
import time

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

NEWS_URL = "https://finnhub.io/api/v1/news"

# TTL del cache de noticias -- el feed general de Finnhub se actualiza
# seguido durante la sesión. 5 min es suficiente para no perderse nada
# relevante sin pegarle a la API en cada carga de la pestaña News (varios
# usuarios pueden tenerla abierta a la vez).
NEWS_CACHE_TTL_SECONDS = 300

# Mismo patrón ya usado en marketdata_client.py/forexfactory_client.py,
# que faltaba acá -- sin esto, una vez que el cache vence, CUALQUIER
# apertura de la pestaña News (de cualquier usuario) durante una caída/
# rate-limit sostenido de Finnhub vuelve a golpear la API sin ningún
# backoff. Más corto que las otras integraciones (5 min, no 300-600s):
# esto no corre en un tick de 2s como Schwab, solo cuando alguien abre la
# pestaña, así que el riesgo de ráfaga es mucho menor.
FAILURE_COOLDOWN_SECONDS = 300
_last_attempt: float = 0.0

_cache: dict[str, tuple[float, list[dict]]] = {}


async def fetch_market_news() -> list[dict]:
    """Feed de noticias de mercado en general (Finnhub, categoría
    'general') -- CRUDO, sin filtrar por relevancia todavía (ver
    domain/news_filter.py::filter_relevant_news, que hace ese trabajo
    para GET /market/news). Finnhub NO da qué ticker impacta cada
    noticia en este endpoint (a diferencia de FinancialJuice, que es
    propietario de ese tageo) -- por eso el filtrado real vive aparte,
    en domain/, como una heurística por palabras clave.

    Nota: el calendario económico YA NO vive acá (ver
    integrations/forexfactory_client.py) -- el endpoint de Finnhub para
    eso devuelve 403 "You don't have access to this resource." en el
    tier gratis, confirmado en vivo (13-sep-2026), a pesar de lo que
    decía la documentación pública. El de noticias (este) sí funciona
    bien en el tier gratis.

    Cache de NEWS_CACHE_TTL_SECONDS -- []/None si no hay API key o el
    fetch falla, mismo criterio que el resto de este módulo.

    Cada item: {"headline", "summary", "url", "source",
    "datetime" (epoch segundos), "image"}."""
    settings = get_settings()
    if not settings.finnhub_api_key:
        return []

    global _last_attempt
    cache_key = "general"
    cached = _cache.get(cache_key)
    if cached is not None and (time.time() - cached[0]) < NEWS_CACHE_TTL_SECONDS:
        return cached[1]

    if (time.time() - _last_attempt) < FAILURE_COOLDOWN_SECONDS:
        return cached[1] if cached is not None else []
    _last_attempt = time.time()

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
