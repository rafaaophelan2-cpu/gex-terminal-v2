import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from app.domain.ai_prompt import build_intraday_context
from app.domain.implied_range import compute_implied_range
from app.domain.metrics import compute_metrics_for_dte
from app.domain.session_profile import SESSION_TZ, cash_key_for, overnight_key_for
from app.integrations.firebase_client import fetch_session_profile
from app.integrations.forexfactory_client import fetch_economic_calendar
from app.integrations.schwab_client import fetch_price_history, fetch_vix, fetch_vix_term_structure
from app.services.cross_check import fetch_ndx_compounded_levels, fetch_vix_gamma_levels, format_ndx_cross_check_text
from app.services.market_feed import feed_registry

NY_TZ = ZoneInfo("America/New_York")


def dte_from_exp_key(exp_key: str | None) -> float:
    """'2026-09-14:2' -> 2.0 -- mismo formato que ya usa el resto del
    sistema (ver domain/parsing.py). Si no se puede parsear, se asume
    0DTE (el peor caso para el ancho de la banda, nunca el mejor)."""
    if not exp_key or ":" not in exp_key:
        return 0.0
    try:
        return float(exp_key.rsplit(":", 1)[-1])
    except ValueError:
        return 0.0


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

    # Se captura UNA vez acá y se reusa esta variable local en TODO lo que
    # sigue -- antes 'metrics'/'ndx_compounded' (arriba, antes del
    # gather) y 'candles'/'implied_range'/el "spot" final (abajo, DESPUÉS
    # del gather) leían feed.spot_price por separado. El gather de más
    # abajo puede tardar varios segundos (llamadas a Schwab serializadas
    # detrás de un lock único, ver schwab_client.py), y el tick de fondo
    # de este mismo feed sigue corriendo cada ~2s mientras tanto -- sin
    # esto, el prompt de la IA podía terminar mezclando walls calculados
    # contra un spot de UN instante con un "precio actual" declarado de
    # un instante posterior, un desajuste real aunque sutil.
    spot = feed.spot_price

    exp_keys = [feed.nearest_exp_key] if feed.nearest_exp_key else []
    metrics = compute_metrics_for_dte(feed.df, exp_keys, spot)
    # compute_metrics_for_dte no sabe nada del percentil REAL que
    # iv_percentile_updater_loop calcula contra el historial de Supabase
    # (ver market_feed.SymbolFeed._iv_rank_is_real) -- sin este override
    # el diagnóstico de la IA seguiría mostrando la fórmula estimada aunque
    # el badge de la barra superior ya muestre el percentil real.
    if getattr(feed, "_iv_rank_is_real", False):
        metrics = {**metrics, "iv_rank_str": feed.iv_rank_str}

    today = datetime.now(NY_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    now_lima = datetime.now(SESSION_TZ)
    candles, vix_val, overnight_profile, cash_profile, vix_term_structure, ndx_compounded, vix_gamma_levels, economic_calendar = await asyncio.gather(
        fetch_price_history(symbol, today),
        fetch_vix(),
        fetch_session_profile(overnight_key_for(now_lima)),
        fetch_session_profile(cash_key_for(now_lima)),
        fetch_vix_term_structure(),
        fetch_ndx_compounded_levels(symbol, spot, metrics),
        fetch_vix_gamma_levels(symbol),
        fetch_economic_calendar(),
    )
    intraday_context = build_intraday_context(candles, spot)
    implied_range = compute_implied_range(spot, metrics.get("atm_iv", 0.20), dte_from_exp_key(feed.nearest_exp_key))
    ndx_cross_check = format_ndx_cross_check_text(symbol, ndx_compounded)

    return {
        "spot": spot,
        "metrics": metrics,
        "vix_val": vix_val,
        "intraday_context": intraday_context,
        "overnight_profile": overnight_profile,
        "cash_profile": cash_profile,
        "vix_term_structure": vix_term_structure,
        "ndx_cross_check": ndx_cross_check,
        "implied_range": implied_range,
        "oi_is_volume_proxy": feed.oi_is_volume_proxy,
        "macro_levels": feed.macro_levels,
        "vix_gamma_levels": vix_gamma_levels,
        "economic_calendar": economic_calendar,
    }
