import logging
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

NY_TZ = ZoneInfo("America/New_York")

# Feed público de ForexFactory (vía su CDN, faireconomy.media) -- SIN API
# key, gratis, sin límite de cuenta. Confirmado en vivo (13-sep-2026) que
# el endpoint "oficial" de calendario económico de Finnhub en realidad
# devuelve 403 "You don't have access to this resource." en el tier
# gratis (a pesar de lo que decía la documentación pública) -- se
# reemplaza acá por completo. Es el mismo feed detrás del widget de
# calendario de forexfactory.com (no un scrape de su HTML), pensado para
# consumo programático.
THISWEEK_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# ForexFactory limita este feed a 2 requests cada 5 min por IP (para
# cualquier formato) -- un cache de 30 min deja muchísimo margen incluso
# con el refresco periódico de la pestaña News + cada diagnóstico de IA
# pidiendo el mismo dato.
CACHE_TTL_SECONDS = 1800

# Cooldown mínimo entre INTENTOS (éxito o fallo) -- confirmado en vivo en
# Render (13-sep-2026, "429 Too Many Requests" en CADA pedido): sin esto,
# un solo fallo dejaba _cache sin actualizar, así que el próximo pedido a
# /market/economic-calendar (segundos después, otro usuario o el mismo
# refresco periódico) reintentaba de inmediato, volvía a pisar el límite
# de 2 req/5 min, y así indefinidamente -- un bucle que nunca dejaba
# pasar el tiempo suficiente para que el límite externo se liberara.
# MISMO bug/arreglo que FAILURE_COOLDOWN_SECONDS en marketdata_client.py.
# 600s (10 min), más ancho que la ventana real de 5 min de ForexFactory
# por margen -- el feed IP puede ser compartida con otros servicios de
# Render, así que un solo intento fallido no debe insistir enseguida.
FAILURE_COOLDOWN_SECONDS = 600

RELEVANT_CURRENCY = "USD"
# Los 3 niveles reales de ForexFactory -- 'Holiday' (feriados bancarios,
# sin dato) y vacío ("Non-Economic"/eventos sin impacto asignado) quedan
# afuera, no son útiles para el prompt de la IA ni para el calendario.
RELEVANT_IMPACT = {"low", "medium", "high"}

_cache: dict[str, tuple[float, list[dict]]] = {}
_last_attempt: float = 0.0


def _relevant_week_range(today: date) -> tuple[date, date]:
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


async def _fetch_raw_week() -> list[dict]:
    """GET crudo del feed semanal, con su propio cache corto (ver
    CACHE_TTL_SECONDS) -- separado de fetch_economic_calendar de abajo
    porque el feed en sí es SIEMPRE "esta semana calendario" según
    ForexFactory (domingo a sábado), y el recorte a la semana relevante
    del usuario (lunes-domingo, con el corrimiento de fin de semana) se
    hace aparte, sobre el mismo payload cacheado.

    Respeta FAILURE_COOLDOWN_SECONDS entre intentos (éxito o fallo) --
    sin esto, un 429 dejaba _cache sin actualizar, así que el próximo
    pedido reintentaba de inmediato y volvía a pisar el límite externo,
    sin nunca dejar pasar tiempo suficiente para que se liberara."""
    global _last_attempt

    cache_key = "raw"
    cached = _cache.get(cache_key)
    if cached is not None and (time.time() - cached[0]) < CACHE_TTL_SECONDS:
        return cached[1]

    if (time.time() - _last_attempt) < FAILURE_COOLDOWN_SECONDS:
        return cached[1] if cached is not None else []
    _last_attempt = time.time()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(THISWEEK_URL, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("forexfactory_client._fetch_raw_week() falló -- se mantiene el cache anterior si hay.")
        return cached[1] if cached is not None else []

    if not isinstance(data, list):
        return cached[1] if cached is not None else []

    _cache[cache_key] = (time.time(), data)
    return data


async def fetch_economic_calendar() -> list[dict]:
    """Eventos macro de EE.UU. (USD) de la semana relevante (ver
    _relevant_week_range -- semana actual en día hábil, semana siguiente
    en fin de semana), hora de Nueva York. Usado tanto por GET
    /market/economic-calendar (pestaña News) como por el prompt de la IA
    (ver services/ai_context.py) -- mismo calendario para ambos, así el
    bot puede razonar sobre catalizadores de DÍAS por delante (no solo
    los de hoy), igual que un analista de order flow real.

    []  si el fetch falla -- opcional igual que MarketData.app (ver
    marketdata_client.py): nunca debe bloquear el resto del diagnóstico
    de la IA.

    Cada item: {"date": "2026-09-16", "time": "08:30" (hora NY),
    "event": str, "impact": "low"|"medium"|"high",
    "actual": str|None, "forecast": str|None, "previous": str|None}."""
    raw = await _fetch_raw_week()
    if not raw:
        return []

    # today = HOY real, no el "hoy" implícito del feed (que puede ya
    # estar mostrando la semana siguiente él solo cerca del fin de
    # semana) -- se recorta explícitamente al rango que el usuario pidió,
    # para que el comportamiento sea determinístico sin depender de
    # cuándo exactamente ForexFactory rota su archivo semanal.
    today = datetime.now(NY_TZ).date()
    week_start, week_end = _relevant_week_range(today)
    week_start_str = week_start.isoformat()
    week_end_str = week_end.isoformat()

    events: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("country") != RELEVANT_CURRENCY:
            continue
        impact = str(item.get("impact") or "").lower()
        if impact not in RELEVANT_IMPACT:
            continue
        # 'date' viene como ISO8601 CON el offset de hora de Nueva York ya
        # embebido (ej. "2026-09-16T08:30:00-04:00" -- ForexFactory
        # siempre publica en hora del Este, y el offset ya refleja
        # EDT/EST según la época del año) -- se puede cortar el string
        # directo sin volver a hacer conversión de huso horario, mismo
        # criterio que ya usaba el campo 'time' de Finnhub.
        raw_date = str(item.get("date") or "")
        if len(raw_date) < 16:
            continue
        date_part, time_part = raw_date[:10], raw_date[11:16]
        if not (week_start_str <= date_part <= week_end_str):
            continue

        events.append({
            "date": date_part,
            "time": time_part,
            "event": str(item.get("title") or "Evento económico"),
            "impact": impact,
            "actual": item.get("actual") or None,
            "forecast": item.get("forecast") or None,
            "previous": item.get("previous") or None,
        })

    events.sort(key=lambda e: (e["date"], e["time"]))
    return events
