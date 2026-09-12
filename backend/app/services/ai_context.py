import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from app.domain.ai_prompt import build_intraday_context
from app.domain.metrics import compute_metrics_for_dte
from app.domain.session_profile import SESSION_TZ, cash_key_for, overnight_key_for
from app.integrations.firebase_client import fetch_session_profile
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
    # compute_metrics_for_dte no sabe nada del percentil REAL que
    # iv_percentile_updater_loop calcula contra el historial de Supabase
    # (ver market_feed.SymbolFeed._iv_rank_is_real) -- sin este override
    # el diagnóstico de la IA seguiría mostrando la fórmula estimada aunque
    # el badge de la barra superior ya muestre el percentil real.
    if getattr(feed, "_iv_rank_is_real", False):
        metrics = {**metrics, "iv_rank_str": feed.iv_rank_str}

    today = datetime.now(NY_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    now_lima = datetime.now(SESSION_TZ)
    candles, vix_val, overnight_profile, cash_profile = await asyncio.gather(
        fetch_price_history(symbol, today),
        fetch_vix(),
        fetch_session_profile(overnight_key_for(now_lima)),
        fetch_session_profile(cash_key_for(now_lima)),
    )
    intraday_context = build_intraday_context(candles, feed.spot_price)

    return {
        "spot": feed.spot_price,
        "metrics": metrics,
        "vix_val": vix_val,
        "intraday_context": intraday_context,
        "overnight_profile": overnight_profile,
        "cash_profile": cash_profile,
    }
