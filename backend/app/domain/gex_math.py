import numpy as np
import pandas as pd
from scipy.stats import norm

RISK_FREE_RATE = 0.045

# IV y tiempo a vencimiento con los que se calcula HOY todo el gamma de la
# app (GEX por strike, perfil de precio, flip). Son un supuesto fijo, no la
# IV/DTE real de cada contrato -- pendiente de reemplazar por los datos
# por contrato que ya manda Schwab. Viven acá (y market_feed los
# reexporta) para que el flip use EXACTAMENTE el mismo supuesto que el
# gráfico de "Gamma Price Profile": si no, el flip y el cruce que se ve en
# ese gráfico podrían no coincidir.
DEFAULT_IV = 0.20
DEFAULT_T_EXP = 1 / 365

# Búsqueda del flip (ver compute_gamma_flip): ±10% alrededor del spot, en
# pasos de 0.05% del spot (~0.37 USD con QQQ en 740). Más allá de ±10% un
# cruce no es un nivel operable intradía, y con 401 precios la búsqueda es
# una sola multiplicación de matrices (strikes x precios), barata aun en el
# free tier.
FLIP_SEARCH_PCT = 0.10
FLIP_GRID_POINTS = 401


def _bs_gamma(spot, strikes: np.ndarray, t_exp: float, iv: float) -> np.ndarray:
    """Gamma de Black-Scholes por strike. 'spot' puede ser un escalar o un
    vector columna (n_precios x 1) para evaluar muchos precios hipotéticos
    de una sola vez -- el resultado se broadcastea contra 'strikes'."""
    iv = max(float(iv), 0.001)
    t_exp = max(float(t_exp), 1e-5)
    vol_sqrt_t = iv * np.sqrt(t_exp)
    with np.errstate(divide='ignore', invalid='ignore'):
        d1 = (np.log(spot / strikes) + (RISK_FREE_RATE + 0.5 * iv ** 2) * t_exp) / vol_sqrt_t
        gamma = norm.pdf(d1) / (spot * vol_sqrt_t)
    return np.where(strikes > 0, gamma, 0.0)


def recalculate_gex_for_spot(df_input: pd.DataFrame, spot_t: float, t_exp: float, iv: float) -> pd.DataFrame:
    """Recalcula gamma/call_gex/put_gex/net_gex vía Black-Scholes para el
    spot actual. Port de recalculate_gex_for_spot en app.py (~línea 1417),
    vectorizado con NumPy en vez del df.apply(axis=1) original — mismo
    resultado, más barato en CPU (relevante en el free tier de 0.25 vCPU
    del host de producción)."""
    if df_input.empty or spot_t <= 0:
        return df_input

    df_out = df_input.copy()
    strikes = df_out['strike'].to_numpy(dtype=float)
    gamma = _bs_gamma(spot_t, strikes, t_exp, iv)

    df_out['gamma'] = gamma
    # *100: multiplicador de contrato (1 contrato = 100 acciones/unidades),
    # el mismo que YA usan net_dex/net_tex/net_vex/net_chex/net_vanna en
    # compute_greeks_exposures (abajo) -- faltaba acá, ver
    # gex_terminal_v2_lessons para el bug real y su blast radius.
    df_out['call_gex'] = df_out['gamma'] * df_out['openInterest_c'] * 100 * (spot_t ** 2) * 0.01
    df_out['put_gex'] = df_out['gamma'] * df_out['openInterest_p'] * 100 * (spot_t ** 2) * (-0.01)
    df_out['net_gex'] = df_out['call_gex'] + df_out['put_gex']
    return df_out


def compute_greeks_exposures(df_input: pd.DataFrame, spot_price: float, t_exp: float, atm_iv: float) -> pd.DataFrame:
    """Agrega DEX/TEX/VEX/CHEX/VANNA por strike. Port directo del bloque de
    app.py (~línea 1519), mismas fórmulas."""
    if df_input.empty or spot_price <= 0:
        return df_input

    df = df_input.copy()

    df['call_dex'] = df['delta_c'] * df['openInterest_c'] * 100 * spot_price / 1e6
    df['put_dex'] = df['delta_p'] * df['openInterest_p'] * 100 * spot_price / 1e6
    df['net_dex'] = (df['call_dex'] + df['put_dex']).fillna(0.0)

    df['call_tex'] = df['theta_c'] * df['openInterest_c'] * 100
    df['put_tex'] = df['theta_p'] * df['openInterest_p'] * 100
    df['net_tex'] = (df['call_tex'] + df['put_tex']).fillna(0.0)

    df['call_vex'] = df['vega_c'] * df['openInterest_c'] * 100
    df['put_vex'] = df['vega_p'] * df['openInterest_p'] * 100
    df['net_vex'] = (df['call_vex'] + df['put_vex']).fillna(0.0)

    atm_iv = max(float(atm_iv), 0.001)
    t_exp = max(float(t_exp), 1e-5)
    vol_sqrt_t = atm_iv * np.sqrt(t_exp)

    valid_strikes = df['strike'] > 0
    strikes_valid = df.loc[valid_strikes, 'strike']
    d1_calc = (np.log(spot_price / strikes_valid) + (RISK_FREE_RATE + 0.5 * atm_iv ** 2) * t_exp) / vol_sqrt_t
    d2_calc = d1_calc - vol_sqrt_t

    call_charm_annual = -norm.pdf(d1_calc) * (RISK_FREE_RATE / vol_sqrt_t - d2_calc / (2.0 * t_exp))
    put_charm_annual = call_charm_annual + (RISK_FREE_RATE * np.exp(-RISK_FREE_RATE * t_exp) * norm.cdf(-d1_calc))

    df.loc[valid_strikes, 'charm_c'] = call_charm_annual / 365.0
    df.loc[valid_strikes, 'charm_p'] = put_charm_annual / 365.0
    df['charm_c'] = df['charm_c'].fillna(0.0)
    df['charm_p'] = df['charm_p'].fillna(0.0)

    df['call_chex'] = df['charm_c'] * df['openInterest_c'] * 100 * spot_price / 1e6
    df['put_chex'] = df['charm_p'] * df['openInterest_p'] * 100 * spot_price / 1e6
    df['net_chex'] = (df['call_chex'] + df['put_chex']).fillna(0.0)

    vanna_val = -norm.pdf(d1_calc) * d2_calc / atm_iv
    df.loc[valid_strikes, 'vanna_c'] = vanna_val
    df.loc[valid_strikes, 'vanna_p'] = vanna_val
    df['vanna_c'] = df['vanna_c'].fillna(0.0)
    df['vanna_p'] = df['vanna_p'].fillna(0.0)

    df['call_vanna'] = df['vanna_c'] * df['openInterest_c'] * 100 * spot_price / 1e6
    df['put_vanna'] = df['vanna_p'] * df['openInterest_p'] * 100 * spot_price / 1e6
    df['net_vanna'] = (df['call_vanna'] + df['put_vanna']).fillna(0.0)

    return df


def compute_call_put_walls(df_grouped: pd.DataFrame, spot_ref: float, gap: float = 2.0):
    """Call Wall / Put Wall por dominancia de signo del net_gex agrupado
    por strike. Port directo de compute_call_put_walls en app.py
    (~línea 1438). df_grouped debe tener una sola fila por strike.

    Un wall que no existe se devuelve como None (26-sep-2026). Antes se
    FABRICABA: sin strikes positivos, CW1 salía como spot + 5; sin un
    segundo strike positivo, CW2 salía como CW1 + 5; y así. Esos números
    no tenían ningún open interest detrás, pero llegaban a la web, a
    Quantower y al briefing con el mismo aspecto que un wall real. Quien
    muestra un wall ahora decide cómo mostrar su ausencia ('--' en la web,
    0 en Quantower, que ya no dibuja niveles <= 0). 'spot_ref' y 'gap'
    quedan en la firma para no romper a quien los pasa."""
    if df_grouped is None or df_grouped.empty or 'net_gex' not in df_grouped.columns:
        return None, None, None, None, None, None

    def _top3(side: pd.DataFrame, ascending: bool) -> list:
        strikes = side.sort_values('net_gex', ascending=ascending)['strike'].tolist()[:3]
        return [float(s) for s in strikes] + [None] * (3 - len(strikes))

    cw1, cw2, cw3 = _top3(df_grouped[df_grouped['net_gex'] > 0], ascending=False)
    pw1, pw2, pw3 = _top3(df_grouped[df_grouped['net_gex'] < 0], ascending=True)
    return cw1, cw2, cw3, pw1, pw2, pw3


def compute_gamma_wall(df_grouped: pd.DataFrame, spot_ref: float) -> float | None:
    """Strike con mayor gamma expuesto en VALOR ABSOLUTO (|call_gex| +
    |put_gex|), a diferencia de Call Wall / Put Wall (compute_call_put_walls,
    arriba) que miran el net_gex con signo. Un strike con, por ejemplo, 10M
    en calls y 10M en puts se cancela a 0 en net_gex y nunca aparecería como
    wall, pero sigue siendo el strike con más actividad de gamma en juego --
    eso es lo que el Gamma Wall captura. df_grouped debe tener una fila por
    strike con columnas 'call_gex' y 'put_gex' ya agregadas (ver
    domain/quantower.py::build_live_levels_payload).

    None cuando no hay datos para calcularlo (antes devolvía el spot, que
    se dibujaba como si fuera un Gamma Wall real)."""
    if df_grouped is None or df_grouped.empty:
        return None
    if 'call_gex' not in df_grouped.columns or 'put_gex' not in df_grouped.columns:
        return None

    abs_exposure = df_grouped['call_gex'].abs() + df_grouped['put_gex'].abs()
    if abs_exposure.empty or abs_exposure.max() <= 0:
        return None

    idx = abs_exposure.idxmax()
    return float(df_grouped.loc[idx, 'strike'])


def _nearest_sign_change(xs: np.ndarray, ys: np.ndarray, target: float) -> float | None:
    """Punto donde la serie 'ys' (sobre 'xs', ordenado) cambia de signo, el
    más cercano a 'target', interpolado linealmente entre los dos puntos
    que lo encierran. Los valores despreciables (|y| <= 1e-9 del máximo)
    no cuentan como signo: en las colas de una curva de gamma el valor es
    prácticamente cero y el ruido numérico de ese cero no es un cruce.
    None si la serie no cambia de signo en ningún lado."""
    if len(xs) < 2:
        return None
    scale = float(np.max(np.abs(ys))) if len(ys) else 0.0
    if scale <= 0 or not np.isfinite(scale):
        return None
    signed = [(float(x), float(y)) for x, y in zip(xs, ys) if abs(y) > scale * 1e-9]

    crossings = []
    for (x0, y0), (x1, y1) in zip(signed, signed[1:]):
        if (y0 < 0) != (y1 < 0):
            crossings.append(x0 + (x1 - x0) * (y0 / (y0 - y1)))
    if not crossings:
        return None
    return min(crossings, key=lambda c: abs(c - target))


def compute_gamma_flip(
    df: pd.DataFrame,
    spot_ref: float,
    t_exp: float = DEFAULT_T_EXP,
    iv: float = DEFAULT_IV,
) -> float | None:
    """Gamma Flip / Zero Gamma en su definición estándar: el PRECIO al que
    el gamma total de los dealers cambiaría de signo si el subyacente
    estuviera ahí, con el open interest de hoy. Es el mismo cálculo que
    dibuja el gráfico "Gamma Price Profile" (ver
    domain/gamma_price_profile.py), así que el flip cae exactamente donde
    esa curva cruza cero.

    Reemplaza (26-sep-2026) al cruce de la suma ACUMULADA por strike, que
    tenía un bug real: tomaba el strike donde |acumulada| era mínima, no
    donde cruzaba cero. Si la acumulada bajaba cerca de cero sin cruzar,
    el flip se quedaba ahí. En vivo ese día marcaba 744.00 (el strike
    ATM) cuando la acumulada cruzaba entre 741 y 742 y el perfil de precio
    cruzaba en ~735.6: ~8 USD de QQQ, ~345 pts de MNQ.

    'df' necesita 'strike', 'openInterest_c' y 'openInterest_p' (una o
    varias filas por strike, se suman). Busca en ±FLIP_SEARCH_PCT del
    spot y devuelve el cruce más cercano al spot, interpolado. None si la
    curva no cruza cero en ese rango: no hay flip real que mostrar, y un
    número inventado (antes: el spot) se leía como un nivel de verdad."""
    needed = {'strike', 'openInterest_c', 'openInterest_p'}
    if df is None or df.empty or not needed.issubset(df.columns) or spot_ref <= 0:
        return None

    by_strike = df.groupby('strike', as_index=False)[['openInterest_c', 'openInterest_p']].sum()
    strikes = by_strike['strike'].to_numpy(dtype=float)
    net_oi = (by_strike['openInterest_c'] - by_strike['openInterest_p']).to_numpy(dtype=float)
    if not np.any(net_oi):
        return None

    prices = np.linspace(spot_ref * (1 - FLIP_SEARCH_PCT), spot_ref * (1 + FLIP_SEARCH_PCT), FLIP_GRID_POINTS)
    gamma = _bs_gamma(prices[:, None], strikes[None, :], t_exp, iv)
    # Misma fórmula que recalculate_gex_for_spot (gamma * OI * 100 * S^2 *
    # 0.01, calls positivas y puts negativas), sumada sobre todos los
    # strikes para cada precio hipotético.
    net_gamma = (gamma * net_oi[None, :]).sum(axis=1) * 100 * prices ** 2 * 0.01
    return _nearest_sign_change(prices, net_gamma, spot_ref)


def compute_zero_crossing(df_by_strike: pd.DataFrame, value_col: str, spot_ref: float) -> float | None:
    """Precio donde la suma acumulada de 'value_col' (ordenado por strike)
    cruza cero -- generalización de compute_zero_gamma (antes hardcodeada a
    'net_gex') para reusar la misma lógica con 'net_chex' y sacar el Charm
    Zero de Aleks Rosme (ver domain/heatmap.py::compute_charm_trend_line),
    sin duplicar el cálculo. Para el gamma, compute_zero_gamma solo cae acá
    cuando no hay open interest para calcular el flip de verdad (snapshots
    viejos).

    Bug real corregido (26-sep-2026): se tomaba idxmin(|acumulada|), el
    strike donde la acumulada quedaba más cerca de cero, que NO es donde
    cruza. Con una acumulada de -41.7M en 740, -32.1M en 741, +11.8M en
    742, +26.7M en 743 y +1.1M en 744, devolvía 744 (se acercó a cero sin
    cruzar) en vez del cruce real entre 741 y 742. Ahora se toma el cambio
    de signo real más cercano al spot, interpolado entre los dos strikes.

    Caso aparte, ya documentado (15-sep-2026): si la acumulada no cruza
    cero en ningún punto, se busca el primer cambio de signo del valor
    CRUDO por strike (ej. net_gex negativo de 698 a 715 y positivo desde
    716 -> 716), como antes.

    None cuando no hay ningún cruce, ni acumulado ni crudo (antes devolvía
    el spot, que se mostraba como si fuera un nivel real)."""
    if df_by_strike is None or df_by_strike.empty or value_col not in df_by_strike.columns:
        return None

    df_sorted = df_by_strike.sort_values('strike')
    strikes = df_sorted['strike'].to_numpy(dtype=float)
    raw = df_sorted[value_col].to_numpy(dtype=float)
    cum_val = np.cumsum(raw)
    if len(cum_val) == 0:
        return None

    crossing = _nearest_sign_change(strikes, cum_val, spot_ref)
    if crossing is not None:
        return crossing

    for i in range(1, len(raw)):
        if (raw[i - 1] < 0 <= raw[i]) or (raw[i - 1] > 0 >= raw[i]):
            return float(strikes[i])
    return None


def compute_zero_gamma(
    df_by_strike: pd.DataFrame,
    spot_ref: float,
    t_exp: float = DEFAULT_T_EXP,
    iv: float = DEFAULT_IV,
) -> float | None:
    """Zero Gamma / Gamma Flip. Con open interest por strike
    ('openInterest_c'/'openInterest_p') usa la definición estándar
    (compute_gamma_flip: dónde cruza cero el gamma total al mover el
    precio). Sin open interest -- los snapshots guardados antes del
    26-sep-2026 solo tienen net_gex -- cae al cruce de la suma acumulada
    por strike (compute_zero_crossing). None si no hay flip real."""
    if df_by_strike is not None and {'openInterest_c', 'openInterest_p'}.issubset(df_by_strike.columns):
        return compute_gamma_flip(df_by_strike, spot_ref, t_exp, iv)
    return compute_zero_crossing(df_by_strike, 'net_gex', spot_ref)
