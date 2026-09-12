import asyncio
import logging
from datetime import datetime, time

from app.domain.gex_math import compute_call_put_walls, compute_zero_gamma
from app.domain.metrics import get_nearest_dte_subset
from app.domain.session_profile import SESSION_TZ
from app.domain.tradingview_string import build_tradingview_levels_string, compute_dominant_gamma_wall
from app.services.market_feed import feed_registry

logger = logging.getLogger(__name__)

UPDATE_INTERVAL_SECONDS = 60

# El usuario pidió explícitamente "que el primer string aparezca a las
# 8:31 y luego se siga actualizando hasta el fin de la sesión (3pm)" --
# un minuto después de la apertura de Cash (8:30, ver session_profile.py),
# no en el mismo instante, para dar tiempo a que el primer tick del día
# ya haya llegado con datos reales.
STRING_WINDOW_START = time(8, 31)
STRING_WINDOW_END = time(15, 0)

# {symbol: {"string": str, "updated_at": "HH:MM:SS", "ticker": str}} --
# estado compartido en memoria, mismo patrón que feed_registry: no
# necesita persistir entre reinicios, se reconstruye solo en el primer
# ciclo después de un restart.
latest_strings: dict[str, dict] = {}


def _build_string_for_feed(feed) -> str | None:
    if feed.df.empty or feed.spot_price <= 0:
        return None

    df_nearest = get_nearest_dte_subset(feed.df)
    by_strike = df_nearest.groupby('strike', as_index=False)[['call_gex', 'put_gex', 'net_gex']].sum().sort_values('strike')
    if by_strike.empty:
        return None

    cw1, cw2, cw3, pw1, pw2, pw3 = compute_call_put_walls(by_strike, feed.spot_price)
    zero_gamma = compute_zero_gamma(by_strike, feed.spot_price)
    dominant_wall = compute_dominant_gamma_wall(by_strike)
    walls = {"cw1": cw1, "cw2": cw2, "cw3": cw3, "pw1": pw1, "pw2": pw2, "pw3": pw3}
    return build_tradingview_levels_string(feed.symbol, walls, zero_gamma, dominant_wall)


async def tradingview_string_updater_loop() -> None:
    """Task de fondo: recalcula el string de niveles para TradingView una
    vez por minuto, SOLO dentro de la ventana 08:31-15:00 hora Lima (Cash
    Session + 1 minuto de margen) -- fuera de ese horario no tiene sentido
    seguir generando strings con datos de una sesión ya cerrada."""
    while True:
        now_lima = datetime.now(SESSION_TZ)
        if STRING_WINDOW_START <= now_lima.time() <= STRING_WINDOW_END:
            for feed in feed_registry.active_feeds():
                try:
                    s = _build_string_for_feed(feed)
                    if s is not None:
                        latest_strings[feed.symbol] = {
                            "symbol": feed.symbol,
                            "string": s,
                            "updated_at": now_lima.strftime("%H:%M:%S"),
                        }
                except Exception:
                    logger.exception("Error generando el string de TradingView para %s -- se reintenta en el próximo ciclo.", feed.symbol)
        await asyncio.sleep(UPDATE_INTERVAL_SECONDS)
