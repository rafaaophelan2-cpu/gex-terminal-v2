import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.domain.briefing_data import (
    build_briefing_payload_from_snapshot,
    build_briefing_payload_live,
    compute_market_status,
    filter_calendar_today,
)
from app.integrations.firebase_client import push_briefing_data
from app.integrations.forexfactory_client import fetch_economic_calendar
from app.integrations.schwab_client import fetch_vix_term_structure
from app.integrations.supabase_client import fetch_gex_history, fetch_latest_snapshot
from app.services.ai_context import dte_from_exp_key
from app.services.market_feed import feed_registry

settings = get_settings()
logger = logging.getLogger(__name__)

# Pedido explícito: cada 30-60s, junto al push de /live_levels (8s, ver
# quantower_pusher.py) -- no necesita esa cadencia, un briefing no se lee
# tick a tick como el indicador de Quantower.
PUSH_INTERVAL_SECONDS = 30

NY_TZ = ZoneInfo("America/New_York")


async def _fetch_today_snapshots(symbol: str) -> list[dict]:
    """Snapshots de HOY (calendario NY) para 'symbol' -- mismo criterio
    de rango que _fetch_day_snapshots en routes_rest.py (día completo en
    NY), usado acá solo para sacar el primero (apertura) y comparar
    contra el Net GEX actual."""
    day_start = datetime.now(NY_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    return await fetch_gex_history(symbol, start_utc=day_start.isoformat(), end_utc=day_end.isoformat(), limit=1000)


async def _push_once() -> None:
    symbol = settings.quantower_symbol
    now_ny = datetime.now(NY_TZ)
    market_status = compute_market_status(now_ny)
    timestamp_utc = datetime.now(ZoneInfo("UTC")).isoformat()
    today_str = now_ny.date().isoformat()

    vix_term_structure, economic_calendar, day_snapshots = await asyncio.gather(
        fetch_vix_term_structure(),
        fetch_economic_calendar(),
        _fetch_today_snapshots(symbol),
    )
    calendar_today = filter_calendar_today(economic_calendar, today_str)
    opening_net_gex = float(day_snapshots[0]["net_gex"]) if day_snapshots else None

    feed = feed_registry.get(symbol)
    if feed is not None and not feed.df.empty and feed.spot_price > 0:
        data_as_of = datetime.fromtimestamp(feed.last_update, tz=ZoneInfo("UTC")).isoformat() if feed.last_update else timestamp_utc
        payload = build_briefing_payload_live(
            symbol, feed.df, feed.spot_price, feed.atm_iv, dte_from_exp_key(feed.nearest_exp_key),
            market_status, timestamp_utc, data_as_of, vix_term_structure, calendar_today, opening_net_gex,
        )
    else:
        # Nadie tiene el dashboard abierto ahora mismo (fuera de horario,
        # o el proceso recién arrancó) -- se cae al último snapshot
        # guardado en Supabase, mismo patrón que GET
        # /market/premarket-briefing. Si tampoco hay NINGÚN snapshot
        # todavía (símbolo nunca usado), no hay nada que empujar.
        snapshot = await fetch_latest_snapshot(symbol)
        if snapshot is None:
            return
        payload = build_briefing_payload_from_snapshot(
            symbol, snapshot, market_status, timestamp_utc, vix_term_structure, calendar_today, opening_net_gex,
        )
        if payload is None:
            return

    await push_briefing_data(symbol, payload)


async def briefing_data_pusher_loop() -> None:
    """Task de fondo: cada PUSH_INTERVAL_SECONDS arma y empuja
    /briefing_data/{symbol} (settings.quantower_symbol, QQQ por defecto)
    a Firebase -- nodo NUEVO, separado de /live_levels (ver
    quantower_pusher.py, que ese SÍ sigue igual). A diferencia de ese
    pusher (que solo actúa mientras hay un SymbolFeed activo), este loop
    corre SIEMPRE: fuera de horario/sin nadie mirando el dashboard cae al
    último snapshot de Supabase (ver domain/briefing_data.py::
    build_briefing_payload_from_snapshot) en vez de dejar el nodo sin
    actualizar -- para que Claude pueda leer 'último cierre conocido'
    incluso de noche/fin de semana, con eso indicado en 'meta'."""
    while True:
        try:
            await _push_once()
        except Exception:
            # Mismo motivo que el resto de los loops de fondo de este
            # proyecto (snapshot_writer.py, quantower_pusher.py): sin
            # loggear acá, un fallo sostenido deja /briefing_data
            # congelado sin ningún rastro visible en Render.
            logger.exception("Error en briefing_data_pusher_loop -- se reintenta en el próximo ciclo.")
        await asyncio.sleep(PUSH_INTERVAL_SECONDS)
