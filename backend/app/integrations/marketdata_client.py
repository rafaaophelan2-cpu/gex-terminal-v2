import asyncio
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.marketdata.app/v1/options/chain"

NY_TZ = ZoneInfo("America/New_York")

# El Open Interest real no varia intradia -- se actualiza UNA vez por
# noche via OCC (Options Clearing Corporation), no en cada trade. Ahora
# que existen los refrescos PROGRAMADOS de pre-mercado y post-cierre
# (ver oi_scheduler.py -- cubren la apertura y una revalidacion nocturna
# por si el OI se corrigio), este refresco oportunista (disparado por
# el tick normal de un SymbolFeed mientras alguien tiene NDX/VIX
# abiertos) pasa a ser solo un colchon adicional durante el dia, no el
# mecanismo principal -- se estira a 6h para dejar el maximo margen
# posible de cupo diario sin usar (pedido explicito: "que quede gas"
# para el resto de la jornada + el dia siguiente). Ver tambien el
# chequeo de fin de semana abajo (_is_weekend_ny): sin eso, un fallo en
# cascada (ya corregido, ver FAILURE_COOLDOWN_SECONDS) o simplemente
# dejar el dashboard abierto un sabado/domingo seguia gastando cuota sin
# necesidad, porque Schwab sirve la ultima chain conocida 24/7 y el feed
# no distinguia el dia.
REFRESH_INTERVAL_SECONDS = 21600

# Cooldown mínimo entre INTENTOS (éxito o fallo) -- confirmado en vivo en
# Render: sin esto, un solo fallo (ej. 429 rate limit) dejaba _cache sin
# actualizar, así que el próximo tick de 2s reintentaba de inmediato, ese
# reintento volvía a fallar, y así indefinidamente -- un bucle que
# mantenía el rate limit pisado para siempre y nunca dejaba pasar el
# tiempo suficiente para que se liberara. Con este cooldown, un fallo
# espera igual antes de volver a intentar.
# 5 min, no 60s: el 429 real visto en producción no fue un rate-limit de
# minuto sino la CUOTA DIARIA de créditos de la cuenta agotada (headers
# x-api-ratelimit-remaining=0, reset varias horas después) -- reintentar
# cada 60s mientras la cuota sigue en 0 solo genera ruido en los logs sin
# ninguna chance real de éxito antes del reset.
FAILURE_COOLDOWN_SECONDS = 300

_cache: dict[str, tuple[float, dict[tuple[float, str], int]]] = {}
_last_attempt: dict[str, float] = {}
_locks: dict[str, asyncio.Lock] = {}


def _is_weekend_ny() -> bool:
    return datetime.now(NY_TZ).weekday() >= 5


async def fetch_oi_map(symbol: str, force: bool = False) -> dict[tuple[float, str], int] | None:
    """Open Interest real por strike para la expiracion mas proxima de
    `symbol`, como {(strike, 'call'|'put'): open_interest} -- pieza que le
    faltaba a Schwab para NDX/VIX (productos de indice exclusivos de CBOE,
    ver oi_fallback.py). Se fusiona en market_feed.py con el spot EN VIVO
    de Schwab para calcular gamma exposure real, no aproximado por
    volumen. None si no hay API key configurada o el fetch fallo sin
    cache previo para devolver -- el caller debe caer al fallback de
    volumen en ese caso.

    'force': salta el chequeo de fin de semana y el de "cache todavia
    fresco" -- para el refresco programado de pre-mercado
    (oi_scheduler.py) y el endpoint manual /market/refresh-oi. El cooldown
    de fallos (FAILURE_COOLDOWN_SECONDS) NO se salta ni con force=True,
    para no permitir que un doble click accidental (o un loop del
    scheduler) generen ráfagas de requests."""
    settings = get_settings()
    if not settings.marketdata_api_key:
        return None

    lock = _locks.setdefault(symbol, asyncio.Lock())
    async with lock:
        cached = _cache.get(symbol)

        # Sábado/domingo: el mercado no abre, así que el OI de ayer sigue
        # siendo el OI de hoy -- no tiene sentido gastar cuota pidiéndolo
        # de nuevo. Devuelve el último cache que haya (aunque sea de
        # varios días, sigue siendo mejor que el proxy de volumen) sin
        # tocar la red.
        if not force and _is_weekend_ny():
            return cached[1] if cached is not None else None

        if not force and cached is not None and (time.time() - cached[0]) < REFRESH_INTERVAL_SECONDS:
            return cached[1]

        last_attempt = _last_attempt.get(symbol, 0.0)
        if (time.time() - last_attempt) < FAILURE_COOLDOWN_SECONDS:
            return cached[1] if cached is not None else None
        _last_attempt[symbol] = time.time()

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.get(
                    f"{BASE_URL}/{symbol}/",
                    params={"token": settings.marketdata_api_key, "dte": 0},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.exception("fetch_oi_map(%s) fallo -- se mantiene el cache anterior si hay.", symbol)
            return cached[1] if cached is not None else None

        if not isinstance(data, dict) or data.get("s") != "ok":
            logger.warning("fetch_oi_map(%s) respuesta no-ok de MarketData.app: %s", symbol, data)
            return cached[1] if cached is not None else None

        strikes = data.get("strike") or []
        sides = data.get("side") or []
        open_interests = data.get("openInterest") or []
        if not strikes or not sides or not open_interests:
            return cached[1] if cached is not None else None

        oi_map: dict[tuple[float, str], int] = {}
        for strike, side, oi in zip(strikes, sides, open_interests):
            key = (float(strike), side)
            oi_map[key] = oi_map.get(key, 0) + int(oi or 0)

        _cache[symbol] = (time.time(), oi_map)
        logger.info("fetch_oi_map(%s): %d strikes actualizados desde MarketData.app.", symbol, len(oi_map))
        return oi_map
