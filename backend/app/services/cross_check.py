import logging

from app.domain.compounded_levels import CompoundedLevel, find_compounded_levels
from app.domain.gex_math import compute_call_put_walls, compute_zero_gamma, recalculate_gex_for_spot
from app.domain.metrics import get_nearest_dte_subset
from app.domain.parsing import parse_schwab_chain
from app.domain.tradingview_string import compute_dominant_gamma_wall
from app.integrations.schwab_client import fetch_option_chain
from app.services.market_feed import DEFAULT_IV, DEFAULT_T_EXP

logger = logging.getLogger(__name__)

# Símbolos "primarios" para los que tiene sentido cruzar contra el libro
# de opciones de NDX (ambos sobre Nasdaq-100, dos pools de open interest
# independientes) -- si el símbolo ya ES NDX (o VIX, que no tiene ese tipo
# de par natural todavía), cruzarlo consigo mismo no aporta nada.
NDX_CROSS_CHECK_SYMBOLS = {"QQQ", "SPY"}
CROSS_CHECK_STRIKES_COUNT = 20


async def fetch_ndx_compounded_levels(primary_symbol: str, primary_spot: float, primary_metrics: dict) -> dict | None:
    """Pide una cadena de NDX FRESCA (no depende de que otro usuario la
    tenga abierta en otra pestaña) y cruza sus niveles contra los del
    símbolo primario -- ver domain/compounded_levels.py. None si el
    símbolo no aplica o el fetch falla; si no, dict con
    {"ratio", "ndx_spot", "matches": list[CompoundedLevel]}."""
    if primary_symbol not in NDX_CROSS_CHECK_SYMBOLS or primary_spot <= 0:
        return None

    try:
        chain = await fetch_option_chain("$NDX", CROSS_CHECK_STRIKES_COUNT)
        df, _ = parse_schwab_chain(chain)
        ndx_spot = float(chain.get("underlyingPrice") or 0.0) if isinstance(chain, dict) else 0.0
        if df.empty or ndx_spot <= 0:
            return None

        df = recalculate_gex_for_spot(df, spot_t=ndx_spot, t_exp=DEFAULT_T_EXP, iv=DEFAULT_IV)
        df_nearest = get_nearest_dte_subset(df)
        by_strike = df_nearest.groupby("strike", as_index=False)[["call_gex", "put_gex", "net_gex"]].sum().sort_values("strike")
        if by_strike.empty:
            return None

        cw1, cw2, cw3, pw1, pw2, pw3 = compute_call_put_walls(by_strike, ndx_spot)
        zero_gamma = compute_zero_gamma(by_strike, ndx_spot)
        dominant_wall = compute_dominant_gamma_wall(by_strike)
    except Exception:
        logger.exception("Cruce de niveles compuestos con NDX falló -- se omite esta vez.")
        return None

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
    return {"ratio": ratio, "ndx_spot": ndx_spot, "matches": matches}


def format_ndx_cross_check_text(primary_symbol: str, result: dict | None) -> str:
    """Texto en prosa para el prompt de la IA -- ver build_system_prompt."""
    if result is None:
        return ""

    ratio = result["ratio"]
    matches: list[CompoundedLevel] = result["matches"]

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
