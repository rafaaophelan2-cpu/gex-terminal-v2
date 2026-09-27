import asyncio
import logging
import time

from app.domain.iv_percentile import compute_iv_percentile
from app.integrations.supabase_client import fetch_daily_atm_iv_history
from app.services.market_feed import feed_registry

logger = logging.getLogger(__name__)

# Cada 5 minutos alcanza de sobra -- el historial diario que consulta
# (fetch_daily_atm_iv_history) solo cambia una vez por día de mercado, no
# hace falta la cadencia de snapshot_writer_loop (60s).
UPDATE_INTERVAL_SECONDS = 300
# Un feed que todavía no tiene percentil real (recién creado, o el backend
# acaba de arrancar y Schwab aún no respondía en la vuelta anterior) se
# reintenta a este ritmo: sin esto la web mostraba "sin historial" hasta 5
# minutos después de cada redeploy aunque el historial existiera. La
# consulta es barata (fetch_daily_atm_iv_history cachea los días cerrados).
PENDING_RETRY_SECONDS = 30

_last_run: dict[str, float] = {}


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
        now = time.monotonic()
        for feed in feed_registry.active_feeds():
            due = UPDATE_INTERVAL_SECONDS if feed._iv_rank_is_real else PENDING_RETRY_SECONDS
            if now - _last_run.get(feed.symbol, float("-inf")) < due:
                continue
            _last_run[feed.symbol] = now
            try:
                await _update_feed(feed)
            except Exception:
                logger.exception("Error actualizando percentil real de IV para %s -- se reintenta en el próximo ciclo.", feed.symbol)
        await asyncio.sleep(PENDING_RETRY_SECONDS)
