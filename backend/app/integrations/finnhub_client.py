import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

BASE_URL = "https://finnhub.io/api/v1/calendar/economic"

NY_TZ = ZoneInfo("America/New_York")

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


async def fetch_economic_calendar() -> list[dict]:
    """Eventos macro de EE.UU. de impacto medio/alto para HOY (hora de
    Nueva York) -- calendario económico de Aleks Rosme (CPI/FOMC/NFP con
    folder rojo/naranja, ver ejemplos que pegó el usuario: "CPI at 8:30
    sent tech higher"). None/[] si no hay API key configurada o el fetch
    falla -- opcional igual que MarketData.app (ver marketdata_client.py):
    nunca debe bloquear el resto del diagnóstico de la IA.

    Cada item: {"time": "08:30" (hora NY o "" si es todo el día),
    "event": str, "impact": "medium"|"high", "actual": str|None,
    "forecast": str|None, "previous": str|None}."""
    settings = get_settings()
    if not settings.finnhub_api_key:
        return []

    today = datetime.now(NY_TZ).date()
    cache_key = today.isoformat()
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                BASE_URL,
                params={
                    "token": settings.finnhub_api_key,
                    "from": today.isoformat(),
                    "to": (today + timedelta(days=1)).isoformat(),
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("fetch_economic_calendar() falló -- se omite el calendario en el prompt esta vez.")
        return []

    raw_events = data.get("economicCalendar") if isinstance(data, dict) else None
    if not isinstance(raw_events, list):
        return []

    today_str = today.isoformat()
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
        # se descarta cualquier evento que no sea de HOY (el rango from/to
        # de arriba puede traer alguno de mañana temprano por huso horario).
        raw_time = str(item.get("time") or "")
        if not raw_time.startswith(today_str):
            continue
        time_part = raw_time.split(" ")[1][:5] if " " in raw_time else ""

        events.append({
            "time": time_part,
            "event": str(item.get("event") or "Evento económico"),
            "impact": impact,
            "actual": item.get("actual"),
            "forecast": item.get("estimate"),
            "previous": item.get("prev"),
        })

    events.sort(key=lambda e: e["time"])
    # Cachea por el resto del día -- el calendario de HOY no cambia salvo
    # que salga el dato 'actual' de un evento ya pasado, y no vale la pena
    # golpear la API de nuevo por cada diagnóstico de IA que se pida
    # (mismo espíritu de cuidado de cuota que MarketData.app).
    _cache[cache_key] = (0.0, events)
    if len(_cache) > 3:
        oldest_key = min(_cache.keys())
        del _cache[oldest_key]
    return events
