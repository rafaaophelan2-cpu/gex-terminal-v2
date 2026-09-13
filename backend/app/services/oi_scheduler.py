import asyncio
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.integrations import marketdata_client
from app.integrations.marketdata_client import fetch_oi_map
from app.services.market_feed import MARKETDATA_OI_SYMBOLS

logger = logging.getLogger(__name__)

NY_TZ = ZoneInfo("America/New_York")

# Ventana de pre-mercado en la que se intenta el refresco diario --
# arranca 30 min antes de la apertura real (09:30 NY = 08:30 Lima) para
# tener margen de reintentos si el primer intento falla, y se corta justo
# en la apertura para no seguir gastando cuota después de que ya no
# aporta nada para "estar listo a la apertura" (si para entonces sigue
# sin éxito, el feed cae al fallback de volumen como siempre, y el
# refresco por hora durante el día -- ver REFRESH_INTERVAL_SECONDS en
# marketdata_client.py -- lo termina resolviendo más tarde).
WINDOW_START = "09:00"
WINDOW_END = "09:30"

# Pedido explícito: si TODOS los intentos de la ventana de arriba
# fallaron, un último intento garantizado ~1 min después de la apertura
# (09:31 NY) en vez de quedarse sin OI real el resto del día hasta el
# próximo refresco por hora. Ventana chica (hasta 09:35) para absorber
# el jitter de CHECK_INTERVAL_SECONDS sin depender de pegarle al minuto
# exacto -- _final_retry_done igual lo acota a un único intento por día.
FINAL_RETRY_START = "09:31"
FINAL_RETRY_END = "09:35"

# 1 min, no 5 -- con la ventana normal ya throttleada por
# FAILURE_COOLDOWN_SECONDS de fetch_oi_map, revisar más seguido acá no
# gasta requests de más (la mayoría de los chequeos son no-ops), y es lo
# que permite pescar la ventana angosta del intento final de arriba.
CHECK_INTERVAL_SECONDS = 60

_last_success_date: dict[str, date] = {}
_final_retry_done: dict[str, date] = {}


async def _try_refresh(symbol: str, today: date) -> None:
    if _last_success_date.get(symbol) == today:
        return
    oi_map = await fetch_oi_map(symbol, force=True)
    if oi_map:
        _last_success_date[symbol] = today
        logger.info("oi_scheduler: refresco de pre-mercado de %s OK para %s (%d strikes).", symbol, today, len(oi_map))


async def _try_final_retry(symbol: str, today: date) -> None:
    if _last_success_date.get(symbol) == today or _final_retry_done.get(symbol) == today:
        return
    _final_retry_done[symbol] = today  # se marca ANTES de intentar -- un único intento final, haya salido bien o mal.

    # fetch_oi_map(force=True) saltea el corte de fin de semana y el
    # "cache todavía fresco", pero a propósito NO el cooldown de fallos
    # (para blindar /market/refresh-oi de un doble-click accidental) --
    # acá sí conviene saltearlo: es un único intento extra más, acotado a
    # una vez por día por symbol, no una puerta abierta a ráfagas.
    marketdata_client._last_attempt[symbol] = 0.0
    oi_map = await fetch_oi_map(symbol, force=True)
    if oi_map:
        _last_success_date[symbol] = today
        logger.info("oi_scheduler: intento final (post-apertura) de %s OK para %s (%d strikes).", symbol, today, len(oi_map))
    else:
        logger.warning("oi_scheduler: intento final (post-apertura) de %s FALLÓ para %s -- se cae al proxy de volumen hasta el próximo refresco por hora.", symbol, today)


async def oi_daily_refresh_loop() -> None:
    """Task de fondo: garantiza que NDX/VIX tengan Open Interest real
    fresco ANTES de la apertura (09:30 NY / 08:30 Lima), todos los días
    hábiles sin excepción -- fetch_oi_map normal (ver market_feed.py) es
    100% reactivo, solo se dispara desde el tick de un SymbolFeed con al
    menos un subscriptor conectado. Sin este scheduler, si nadie tenía
    NDX o VIX abiertos justo en ese momento, el OI del día podía quedar
    sin pedirse hasta que alguien abriera esa pestaña de casualidad.
    force=True en fetch_oi_map hace que el resultado quede en el cache
    compartido -- cuando alguien abre NDX/VIX más tarde, encuentra el OI
    ya fresco sin gastar un request nuevo.

    Costo real: 2 símbolos, como mucho un puñado de reintentos dentro de
    la ventana de 30 min (bloqueados entre sí por FAILURE_COOLDOWN_SECONDS
    de todas formas) + el intento final de post-apertura -- una fracción
    mínima del cupo diario, dejando margen de sobra para refrescos
    manuales (ver /market/refresh-oi)."""
    while True:
        try:
            now_ny = datetime.now(NY_TZ)
            today = now_ny.date()
            time_str = now_ny.strftime("%H:%M")
            is_weekday = now_ny.weekday() < 5

            if is_weekday:
                if WINDOW_START <= time_str <= WINDOW_END:
                    for symbol in MARKETDATA_OI_SYMBOLS:
                        await _try_refresh(symbol, today)
                elif FINAL_RETRY_START <= time_str <= FINAL_RETRY_END:
                    for symbol in MARKETDATA_OI_SYMBOLS:
                        await _try_final_retry(symbol, today)
        except Exception:
            logger.exception("oi_scheduler: error en el ciclo de refresco de pre-mercado.")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
