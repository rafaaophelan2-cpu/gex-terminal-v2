import asyncio
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.integrations import marketdata_client
from app.integrations.marketdata_client import fetch_oi_map
from app.services.market_feed import MARKETDATA_OI_SYMBOLS

logger = logging.getLogger(__name__)

NY_TZ = ZoneInfo("America/New_York")

# --- Ventana de PRE-MERCADO ---------------------------------------------
# Arranca 30 min antes de la apertura real (09:30 NY = 08:30 Lima) para
# tener margen de reintentos si el primer intento falla, y se corta justo
# en la apertura para no seguir gastando cuota después de que ya no
# aporta nada para "estar listo a la apertura".
MORNING_WINDOW_START = "09:00"
MORNING_WINDOW_END = "09:30"
# Si TODA la ventana de arriba falló, un último intento garantizado ~1
# min después de la apertura (pedido explícito) en vez de quedarse sin OI
# real el resto de la mañana.
MORNING_FINAL_RETRY_START = "09:31"
MORNING_FINAL_RETRY_END = "09:35"

# --- Ventana de REVALIDACIÓN NOCTURNA ------------------------------------
# El OI "oficial" de OCC (Options Clearing Corporation) para el día que
# cerró suele terminar de asentarse recién en la noche, horas después del
# cierre (16:00 NY) -- esta ventana vuelve a pedirlo ~20:00 NY (19:00
# Lima) por si cambió algo respecto al último dato del día, DEJANDO EL
# CACHE LISTO PARA MAÑANA (mismo OI que se usaría en la próxima apertura
# de todas formas, ver REFRESH_INTERVAL_SECONDS en marketdata_client.py).
EVENING_WINDOW_START = "20:00"
EVENING_WINDOW_END = "20:10"
EVENING_FINAL_RETRY_START = "20:11"
EVENING_FINAL_RETRY_END = "20:15"

# 1 min, no 5 -- con las ventanas ya throttleadas por
# FAILURE_COOLDOWN_SECONDS de fetch_oi_map, revisar más seguido acá no
# gasta requests de más (la mayoría de los chequeos son no-ops), y es lo
# que permite pescar las ventanas angostas de arriba sin depender de
# pegarle al minuto exacto.
CHECK_INTERVAL_SECONDS = 60

# Estado por símbolo+día, independiente para cada ventana -- un éxito a
# la mañana NO debe bloquear el intento de la noche (todo lo contrario,
# es justamente cuando se quiere volver a preguntar "¿cambió algo?").
_morning_success_date: dict[str, date] = {}
_morning_final_retry_done: dict[str, date] = {}
_evening_success_date: dict[str, date] = {}
_evening_final_retry_done: dict[str, date] = {}


async def _try_window(symbol: str, today: date, success_state: dict[str, date]) -> bool:
    """Intenta un fetch real (respetando el cooldown normal de fallos) si
    esta ventana todavía no tuvo éxito hoy para `symbol`. Devuelve True si
    ya hay OI fresco de esta ventana (ya sea porque se acaba de conseguir
    o porque ya se había conseguido antes en la misma ventana)."""
    if success_state.get(symbol) == today:
        return True
    oi_map = await fetch_oi_map(symbol, force=True)
    if oi_map:
        success_state[symbol] = today
        return True
    return False


async def _try_final_retry(symbol: str, today: date, success_state: dict[str, date], final_done_state: dict[str, date], label: str) -> None:
    if success_state.get(symbol) == today or final_done_state.get(symbol) == today:
        return
    final_done_state[symbol] = today  # se marca ANTES de intentar -- un único intento final, haya salido bien o mal.

    # fetch_oi_map(force=True) saltea el corte de fin de semana y el
    # "cache todavía fresco", pero a propósito NO el cooldown de fallos
    # (para blindar /market/refresh-oi de un doble-click accidental) --
    # acá sí conviene saltearlo: es un único intento extra más, acotado a
    # una vez por ventana por día, no una puerta abierta a ráfagas.
    marketdata_client._last_attempt[symbol] = 0.0
    ok = await _try_window(symbol, today, success_state)
    if ok:
        logger.info("oi_scheduler: intento final (%s) de %s OK para %s.", label, symbol, today)
    else:
        logger.warning("oi_scheduler: intento final (%s) de %s FALLÓ para %s.", label, symbol, today)


async def oi_daily_refresh_loop() -> None:
    """Task de fondo: garantiza que NDX/VIX tengan Open Interest real
    fresco (1) ANTES de la apertura y (2) revalidado en la noche por si
    el dato oficial cambió, todos los días hábiles sin excepción --
    fetch_oi_map normal (ver market_feed.py) es 100% reactivo, solo se
    dispara desde el tick de un SymbolFeed con al menos un subscriptor
    conectado. Sin este scheduler, si nadie tenía NDX o VIX abiertos justo
    en esos momentos, el OI podía quedar sin pedirse hasta que alguien
    abriera esa pestaña de casualidad. force=True en fetch_oi_map hace
    que el resultado quede en el cache compartido -- cuando alguien abre
    NDX/VIX más tarde, encuentra el OI ya fresco sin gastar un request
    nuevo.

    Costo real por día (2 símbolos): típicamente 2 (mañana, primer
    intento ya funciona) + 2 (noche, ídem) = 4 requests. Peor caso
    (todo falla siempre): ~16 mañana + ~10 noche = 26, todavía muy por
    debajo del cupo diario -- deja margen de sobra para el refresco
    oportunista del día (ver REFRESH_INTERVAL_SECONDS, ahora 6h) y para
    refrescos manuales (ver /market/refresh-oi)."""
    while True:
        try:
            now_ny = datetime.now(NY_TZ)
            today = now_ny.date()
            time_str = now_ny.strftime("%H:%M")
            is_weekday = now_ny.weekday() < 5

            if is_weekday:
                if MORNING_WINDOW_START <= time_str <= MORNING_WINDOW_END:
                    for symbol in MARKETDATA_OI_SYMBOLS:
                        await _try_window(symbol, today, _morning_success_date)
                elif MORNING_FINAL_RETRY_START <= time_str <= MORNING_FINAL_RETRY_END:
                    for symbol in MARKETDATA_OI_SYMBOLS:
                        await _try_final_retry(symbol, today, _morning_success_date, _morning_final_retry_done, "pre-apertura")
                elif EVENING_WINDOW_START <= time_str <= EVENING_WINDOW_END:
                    for symbol in MARKETDATA_OI_SYMBOLS:
                        await _try_window(symbol, today, _evening_success_date)
                elif EVENING_FINAL_RETRY_START <= time_str <= EVENING_FINAL_RETRY_END:
                    for symbol in MARKETDATA_OI_SYMBOLS:
                        await _try_final_retry(symbol, today, _evening_success_date, _evening_final_retry_done, "nocturno")
        except Exception:
            logger.exception("oi_scheduler: error en el ciclo de refresco.")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
