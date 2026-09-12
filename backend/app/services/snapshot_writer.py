import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.domain.drift import DEFAULT_SESSION_END, DEFAULT_SESSION_START
from app.domain.metrics import get_nearest_dte_subset
from app.integrations.supabase_client import insert_gex_snapshot
from app.services.market_feed import feed_registry

logger = logging.getLogger(__name__)

SNAPSHOT_INTERVAL_SECONDS = 60

# Igual que STORAGE_TZ en app.py: el snapshot SIEMPRE se guarda en hora de
# Nueva York, sin importar qué zona horaria tenga elegida cualquier
# usuario en su sidebar -- así el mismo instante real queda etiquetado
# igual sin importar quién lo guardó, y el dedup por symbol+time funciona.
STORAGE_TZ = ZoneInfo("America/New_York")


async def _write_snapshot_for_feed(feed) -> None:
    if not feed.schwab_online or feed.spot_price <= 0 or feed.df.empty:
        return

    now_store = datetime.now(STORAGE_TZ)
    time_str = now_store.strftime("%H:%M")

    # Fuera de horario de mercado, Schwab sigue devolviendo la última
    # chain conocida (call_with_fallback la sirve como "último dato
    # bueno" indefinidamente) -- sin este filtro, el writer graba ese
    # mismo snapshot stale cada minuto toda la noche. Aparte del ruido,
    # esas filas rompían el dedup por symbol+time del día siguiente (ver
    # insert_gex_snapshot) y hacían que available-dates apuntara a un día
    # sin ninguna fila dentro de 09:30-16:00, dejando LIVE GAMMA en
    # blanco hasta que abriera el mercado real.
    if not (DEFAULT_SESSION_START <= time_str <= DEFAULT_SESSION_END):
        return

    # SIEMPRE la expiración más cercana (0DTE), nunca el DTE que cualquier
    # conexión tenga seleccionado en pantalla -- mismo criterio que
    # get_nearest_dte_subset en export_snapshot_throttled de app.py, para
    # que el feed guardado sea determinístico y no dependa de qué esté
    # mirando cada usuario.
    df_nearest = get_nearest_dte_subset(feed.df)
    by_strike = df_nearest.groupby('strike', as_index=False)[['call_gex', 'put_gex', 'net_gex']].sum()

    strikes_payload = [
        {
            "strike": float(row.strike),
            "net_gex": float(row.net_gex),
            "call_gex": float(row.call_gex),
            "put_gex": float(row.put_gex),
        }
        for row in by_strike.itertuples()
    ]

    snapshot = {
        "symbol": feed.symbol,
        "time": time_str,
        "spot": float(feed.spot_price),
        "net_gex": float(by_strike['net_gex'].sum()),
        "strikes": strikes_payload,
        "atm_iv": float(feed.atm_iv),
    }

    await insert_gex_snapshot(snapshot)


async def snapshot_writer_loop() -> None:
    """Task de fondo: guarda un snapshot cada 60s para cada símbolo con
    al menos una conexión activa. Corre independiente de cualquier
    conexión WS en particular -- port de export_snapshot_throttled en
    app.py, adaptado de "una vez por rerun de sesión" a "una vez por
    símbolo activo en el proceso"."""
    while True:
        for feed in feed_registry.active_feeds():
            try:
                await _write_snapshot_for_feed(feed)
            except Exception:
                logger.exception("Error guardando snapshot de %s -- se reintenta en el próximo ciclo.", feed.symbol)
        await asyncio.sleep(SNAPSHOT_INTERVAL_SECONDS)
