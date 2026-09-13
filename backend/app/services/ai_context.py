import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.domain.ai_prompt import build_intraday_context
from app.domain.compounded_levels import find_compounded_levels
from app.domain.gex_math import compute_call_put_walls, compute_zero_gamma, recalculate_gex_for_spot
from app.domain.implied_range import compute_implied_range
from app.domain.metrics import compute_metrics_for_dte, get_nearest_dte_subset
from app.domain.parsing import parse_schwab_chain
from app.domain.session_profile import SESSION_TZ, cash_key_for, overnight_key_for
from app.domain.tradingview_string import compute_dominant_gamma_wall
from app.integrations.firebase_client import fetch_session_profile
from app.integrations.schwab_client import fetch_option_chain, fetch_price_history, fetch_vix, fetch_vix_term_structure
from app.services.market_feed import DEFAULT_IV, DEFAULT_T_EXP, feed_registry

NY_TZ = ZoneInfo("America/New_York")
logger = logging.getLogger(__name__)

# Símbolos "primarios" para los que tiene sentido cruzar contra el libro
# de opciones de NDX (ambos sobre Nasdaq-100, dos pools de open interest
# independientes) -- si el símbolo ya ES NDX (o VIX, que no tiene ese
# tipo de par natural todavía), cruzarlo consigo mismo no aporta nada.
NDX_CROSS_CHECK_SYMBOLS = {"QQQ", "SPY"}
CROSS_CHECK_STRIKES_COUNT = 20


def _dte_from_exp_key(exp_key: str | None) -> float:
    """'2026-09-14:2' -> 2.0 -- mismo formato que ya usa el resto del
    sistema (ver domain/parsing.py). Si no se puede parsear, se asume
    0DTE (el peor caso para el ancho de la banda, nunca el mejor)."""
    if not exp_key or ":" not in exp_key:
        return 0.0
    try:
        return float(exp_key.rsplit(":", 1)[-1])
    except ValueError:
        return 0.0


async def _fetch_ndx_cross_check(primary_symbol: str, primary_spot: float, primary_metrics: dict) -> str:
    """Cruce de niveles compuestos contra NDX (ver domain/compounded_levels.py)
    -- se pide una cadena de NDX FRESCA en cada llamada (no depende de que
    algún otro usuario tenga NDX abierto en otra pestaña) porque el chat
    es de uso esporádico, no un tick de 2s: el costo extra de un fetch
    puntual a Schwab es aceptable acá y mantiene el cruce siempre
    disponible en vez de contingente al estado de otra conexión WS."""
    if primary_symbol not in NDX_CROSS_CHECK_SYMBOLS or primary_spot <= 0:
        return ""

    try:
        chain = await fetch_option_chain("$NDX", CROSS_CHECK_STRIKES_COUNT)
        df, _ = parse_schwab_chain(chain)
        ndx_spot = float(chain.get("underlyingPrice") or 0.0) if isinstance(chain, dict) else 0.0
        if df.empty or ndx_spot <= 0:
            return ""

        df = recalculate_gex_for_spot(df, spot_t=ndx_spot, t_exp=DEFAULT_T_EXP, iv=DEFAULT_IV)
        df_nearest = get_nearest_dte_subset(df)
        by_strike = df_nearest.groupby("strike", as_index=False)[["call_gex", "put_gex", "net_gex"]].sum().sort_values("strike")
        if by_strike.empty:
            return ""

        cw1, cw2, cw3, pw1, pw2, pw3 = compute_call_put_walls(by_strike, ndx_spot)
        zero_gamma = compute_zero_gamma(by_strike, ndx_spot)
        dominant_wall = compute_dominant_gamma_wall(by_strike)
    except Exception:
        logger.exception("Cruce de niveles compuestos con NDX falló -- se omite esta vez, no bloquea el resto del contexto.")
        return ""

    ratio = ndx_spot / primary_spot
    primary_levels = {
        "Call Wall 1": primary_metrics.get("cw1"), "Call Wall 2": primary_metrics.get("cw2"), "Call Wall 3": primary_metrics.get("cw3"),
        "Put Wall 1": primary_metrics.get("pw1"), "Put Wall 2": primary_metrics.get("pw2"), "Put Wall 3": primary_metrics.get("pw3"),
        "Zero Gamma": primary_metrics.get("zero_gamma"), "Gamma Wall": primary_metrics.get("dominant_wall"),
    }
    secondary_levels = {
        "Call Wall 1 NDX": cw1, "Call Wall 2 NDX": cw2, "Call Wall 3 NDX": cw3,
        "Put Wall 1 NDX": pw1, "Put Wall 2 NDX": pw2, "Put Wall 3 NDX": pw3,
        "Zero Gamma NDX": zero_gamma, "Gamma Wall NDX": dominant_wall,
    }
    matches = find_compounded_levels(primary_levels, secondary_levels, ratio, primary_spot)

    if not matches:
        return (
            f"CRUCE CON NDX (niveles compuestos): se comparó el mapa de gamma de {primary_symbol} contra el de NDX "
            f"(dos libros de open interest independientes sobre Nasdaq-100, ratio NDX/{primary_symbol} actual "
            f"{ratio:.2f}) y NINGÚN nivel coincide entre ambos ahora mismo -- no hay refuerzo cruzado hoy, tratá los "
            f"niveles de {primary_symbol} como el único libro disponible, sin ese plus de convicción."
        )

    lines = "\n".join(
        f"  - {m.primary_name} de {primary_symbol} ({m.primary_value:.2f}) coincide con {m.secondary_name} "
        f"(equivalente {m.secondary_value_translated:.2f} en escala {primary_symbol})"
        for m in matches
    )
    return (
        "CRUCE CON NDX (niveles compuestos -- en el framework de Aleks Rosme esto es su 'bread and butter'): cuando el "
        f"mismo precio muestra gamma grande en DOS libros de open interest independientes sobre el mismo mercado "
        f"({primary_symbol} y NDX, ambos Nasdaq-100), ese nivel tiene MÁS prioridad que uno que aparece en un solo "
        f"libro. Dale más convicción a cualquier setup que use uno de estos niveles compuestos, y dilo explícitamente "
        f"si tu escenario elegido coincide con uno:\n{lines}"
    )


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
    candles, vix_val, overnight_profile, cash_profile, vix_term_structure, ndx_cross_check = await asyncio.gather(
        fetch_price_history(symbol, today),
        fetch_vix(),
        fetch_session_profile(overnight_key_for(now_lima)),
        fetch_session_profile(cash_key_for(now_lima)),
        fetch_vix_term_structure(),
        _fetch_ndx_cross_check(symbol, feed.spot_price, metrics),
    )
    intraday_context = build_intraday_context(candles, feed.spot_price)
    implied_range = compute_implied_range(feed.spot_price, metrics.get("atm_iv", 0.20), _dte_from_exp_key(feed.nearest_exp_key))

    return {
        "spot": feed.spot_price,
        "metrics": metrics,
        "vix_val": vix_val,
        "intraday_context": intraday_context,
        "overnight_profile": overnight_profile,
        "cash_profile": cash_profile,
        "vix_term_structure": vix_term_structure,
        "ndx_cross_check": ndx_cross_check,
        "implied_range": implied_range,
    }
