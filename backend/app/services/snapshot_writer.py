import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from app.domain.metrics import get_nearest_dte_subset
from app.integrations.supabase_client import insert_gex_snapshot
from app.services.market_feed import feed_registry

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
                pass  # Fase 4: loggear a console_logs (Supabase)
        await asyncio.sleep(SNAPSHOT_INTERVAL_SECONDS)
