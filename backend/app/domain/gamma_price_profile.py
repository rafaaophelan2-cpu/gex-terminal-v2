from app.domain.gex_math import recalculate_gex_for_spot

import math

# Tope del rango alrededor del spot que cubre la curva. Antes era el rango
# FIJO: con QQQ (cadena de ±15 strikes de 1 USD, ~±2%) la curva ocupaba
# ~15% del ancho del gráfico y el resto eran colas planas en cero
# (auditoría 26-sep-2026). Ahora el rango sale de la propia cadena: los
# strikes extremos más 3 desvíos del movimiento esperado (ahí el gamma ya
# se apagó), con este valor como tope -- que sigue haciendo falta para VIX,
# cuyos strikes de 0.5-1 sobre ~16 cubren un porcentaje enorme.
DEFAULT_PCT_RANGE = 0.18
MIN_PCT_RANGE = 0.02
DEFAULT_NUM_POINTS = 80


def auto_pct_range(strikes, spot_ref: float, t_exp: float, iv: float) -> float:
    """Ancho (fracción del spot a cada lado) que cubre todos los strikes
    de la cadena más 3 desvíos del subyacente, entre MIN y DEFAULT."""
    if spot_ref <= 0 or len(strikes) == 0:
        return DEFAULT_PCT_RANGE
    lo, hi = float(min(strikes)), float(max(strikes))
    reach = max(abs(lo / spot_ref - 1), abs(hi / spot_ref - 1))
    sigma = iv * math.sqrt(max(t_exp, 0.0))
    return min(max(reach + 3 * sigma, MIN_PCT_RANGE), DEFAULT_PCT_RANGE)


def compute_gamma_price_profile(
    df_nearest,
    spot_ref: float,
    t_exp: float,
    iv: float,
    pct_range: float | None = None,
    num_points: int = DEFAULT_NUM_POINTS,
) -> dict:
    """"Gamma Price Profile": Net GEX total proyectado si el spot estuviera
    en cada uno de 'num_points' precios hipotéticos alrededor del actual
    -- a diferencia del gráfico de barras de GEX INFO (Net GEX por strike,
    AL spot de hoy), esto responde "¿cómo cambiaría el gamma total si el
    precio se moviera?", manteniendo fijos el open interest y la IV (por
    eso 'Assumes constant IV' en el subtítulo, igual que la referencia).
    Reusa recalculate_gex_for_spot -- la misma función que ya recalcula
    gamma/GEX para el spot real en cada tick -- una vez por precio
    hipotético; es barato (vectorizado con NumPy, la cadena de opciones
    tiene unas pocas decenas de filas)."""
    empty = {"prices": [], "net_gamma": []}
    if df_nearest is None or df_nearest.empty or spot_ref <= 0 or num_points < 2:
        return empty

    if pct_range is None:
        pct_range = auto_pct_range(df_nearest['strike'].unique(), spot_ref, t_exp, iv)
    lo = spot_ref * (1 - pct_range)
    hi = spot_ref * (1 + pct_range)
    step = (hi - lo) / (num_points - 1)

    prices = []
    net_gamma = []
    for i in range(num_points):
        price = lo + step * i
        recomputed = recalculate_gex_for_spot(df_nearest, spot_t=price, t_exp=t_exp, iv=iv)
        prices.append(round(price, 2))
        net_gamma.append(float(recomputed['net_gex'].sum()))

    return {"prices": prices, "net_gamma": net_gamma}
