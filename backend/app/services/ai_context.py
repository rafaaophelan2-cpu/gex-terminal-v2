import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from app.domain.ai_prompt import build_intraday_context
from app.domain.metrics import compute_metrics_for_dte
from app.integrations.schwab_client import fetch_price_history, fetch_vix
from app.services.market_feed import feed_registry

NY_TZ = ZoneInfo("America/New_York")


class NoActiveFeedError(Exception):
    """El símbolo no tiene ningún SymbolFeed activo todavía -- requiere
    que al menos una conexión WS esté suscrita a él (ver FeedRegistry)."""


async def build_ai_context(symbol: str) -> dict:
    """Contexto compartido por /market/ai-diagnosis y /chat/message: lee
    el SymbolFeed activo (nearest-DTE, determinístico, igual que
    snapshot_writer/quantower_pusher), y junta velas intradía + VIX en
    vivo para el prompt de la IA. Lanza NoActiveFeedError si nadie tiene
    ese símbolo abierto en el dashboard todavía."""
    feed = feed_registry.get(symbol)
    if feed is None or feed.df.empty or feed.spot_price <= 0:
        raise NoActiveFeedError(symbol)

    exp_keys = [feed.nearest_exp_key] if feed.nearest_exp_key else []
    metrics = compute_metrics_for_dte(feed.df, exp_keys, feed.spot_price)

    today = datetime.now(NY_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    candles, vix_val = await asyncio.gather(
        fetch_price_history(symbol, today),
        fetch_vix(),
    )
    intraday_context = build_intraday_context(candles, feed.spot_price)

    return {
        "spot": feed.spot_price,
        "metrics": metrics,
        "vix_val": vix_val,
        "intraday_context": intraday_context,
    }
