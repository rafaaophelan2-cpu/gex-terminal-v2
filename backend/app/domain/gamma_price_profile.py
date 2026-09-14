from app.domain.gex_math import recalculate_gex_for_spot

# Rango alrededor del spot actual que cubre la curva -- lo bastante ancho
# para mostrar ambas colas aplanándose (como en la referencia del
# usuario), sin diluir la resolución cerca del spot con un rango excesivo.
DEFAULT_PCT_RANGE = 0.18
DEFAULT_NUM_POINTS = 80


def compute_gamma_price_profile(
    df_nearest,
    spot_ref: float,
    t_exp: float,
    iv: float,
    pct_range: float = DEFAULT_PCT_RANGE,
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
