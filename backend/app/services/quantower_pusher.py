import asyncio
import logging

from app.config import get_settings
from app.domain.quantower import build_live_levels_payload, compute_conversion_ratio
from app.integrations.firebase_client import push_live_levels
from app.integrations.schwab_client import fetch_nq_price
from app.services.market_feed import feed_registry

settings = get_settings()
logger = logging.getLogger(__name__)

PUSH_INTERVAL_SECONDS = 8


async def _push_once() -> None:
    feed = feed_registry.get(settings.quantower_symbol)
    if feed is None:
        return

    nq_price = await fetch_nq_price()
    conversion_ratio = compute_conversion_ratio(nq_price, feed.spot_price)

    payload = build_live_levels_payload(feed.df, feed.spot_price, conversion_ratio)
    if payload is None:
        return

    await push_live_levels(payload)


async def quantower_pusher_loop() -> None:
    """Task de fondo: cada 8s empuja el SymbolFeed de settings.quantower_symbol
    (QQQ por defecto) al nodo /live_levels de Firebase para el indicador
    de Quantower -- port de export_live_levels_to_quantower en app.py,
    adaptado de "una vez por rerun de sesión" a "una vez por proceso".
    Igual que snapshot_writer_loop, no depende de ninguna conexión WS en
    particular, pero SÍ requiere que exista un SymbolFeed activo para
    quantower_symbol (alguien viéndolo en el dashboard) -- misma
    limitación implícita que tenía app.py, que solo empujaba mientras el
    proceso de Streamlit tenía al menos una sesión de navegador corriendo."""
    while True:
        try:
            await _push_once()
        except Exception:
            # Antes se tragaba en silencio -- mismo patrón que ya causó una
            # salida completa de datos indiagnosticable en market_feed.py y
            # schwab_client.py (ver commits de esta sesión), acá con el
            # mismo riesgo: si esto falla sostenido, el indicador de
            # Quantower deja de recibir niveles sin ningún rastro visible.
            # TODO Fase 4: además, loggear a console_logs (Supabase).
            logger.exception("Error en quantower_pusher_loop -- se reintenta en el próximo ciclo.")
        await asyncio.sleep(PUSH_INTERVAL_SECONDS)
