import asyncio
import logging

from app.domain.iv_percentile import compute_iv_percentile
from app.integrations.supabase_client import fetch_daily_atm_iv_history
from app.services.market_feed import feed_registry

logger = logging.getLogger(__name__)

# Cada 5 minutos alcanza de sobra -- el historial diario que consulta
# (fetch_daily_atm_iv_history) solo cambia una vez por día de mercado, no
# hace falta la cadencia de snapshot_writer_loop (60s).
UPDATE_INTERVAL_SECONDS = 300


async def _update_feed(feed) -> None:
    if not feed.schwab_online or feed.atm_iv <= 0:
        return

    history = await fetch_daily_atm_iv_history(feed.symbol)
    real_percentile = compute_iv_percentile(feed.atm_iv, history)
    if real_percentile is not None:
        feed.iv_rank_str = real_percentile
        feed._iv_rank_is_real = True
    # Si todavía no hay suficiente historial (compute_iv_percentile
    # devuelve None), NO se toca _iv_rank_is_real -- se deja que
    # SymbolFeed._recalculate() siga mostrando la fórmula estimada hasta
    # que se acumulen los días mínimos.


async def iv_percentile_updater_loop() -> None:
    """Task de fondo: recalcula el percentil REAL de IV ATM contra el
    historial diario de Supabase para cada símbolo con al menos una
    conexión activa. Separado de snapshot_writer_loop (que corre cada 60s
    y SOLO escribe el atm_iv de hoy) porque este necesita LEER ese
    historial acumulado, algo que no tiene sentido repetir tan seguido."""
    while True:
        for feed in feed_registry.active_feeds():
            try:
                await _update_feed(feed)
            except Exception:
                logger.exception("Error actualizando percentil real de IV para %s -- se reintenta en el próximo ciclo.", feed.symbol)
        await asyncio.sleep(UPDATE_INTERVAL_SECONDS)
