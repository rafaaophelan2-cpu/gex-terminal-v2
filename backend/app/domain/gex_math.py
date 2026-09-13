import numpy as np
import pandas as pd
from scipy.stats import norm

RISK_FREE_RATE = 0.045


def recalculate_gex_for_spot(df_input: pd.DataFrame, spot_t: float, t_exp: float, iv: float) -> pd.DataFrame:
    """Recalcula gamma/call_gex/put_gex/net_gex vía Black-Scholes para el
    spot actual. Port de recalculate_gex_for_spot en app.py (~línea 1417),
    vectorizado con NumPy en vez del df.apply(axis=1) original — mismo
    resultado, más barato en CPU (relevante en el free tier de 0.25 vCPU
    del host de producción)."""
    if df_input.empty or spot_t <= 0:
        return df_input

    df_out = df_input.copy()
    iv = max(float(iv), 0.001)
    t_exp = max(float(t_exp), 1e-5)

    strikes = df_out['strike'].to_numpy(dtype=float)
    vol_sqrt_t = iv * np.sqrt(t_exp)
    with np.errstate(divide='ignore', invalid='ignore'):
        d1 = (np.log(spot_t / strikes) + (RISK_FREE_RATE + 0.5 * iv ** 2) * t_exp) / vol_sqrt_t
        gamma = norm.pdf(d1) / (spot_t * vol_sqrt_t)
    gamma = np.where(strikes > 0, gamma, 0.0)

    df_out['gamma'] = gamma
    df_out['call_gex'] = df_out['gamma'] * df_out['openInterest_c'] * (spot_t ** 2) * 0.01
    df_out['put_gex'] = df_out['gamma'] * df_out['openInterest_p'] * (spot_t ** 2) * (-0.01)
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
    (~línea 1438). df_grouped debe tener una sola fila por strike."""
    if df_grouped is None or df_grouped.empty or 'net_gex' not in df_grouped.columns:
        return (
            spot_ref + gap * 2.5, spot_ref + gap * 5, spot_ref + gap * 7.5,
            spot_ref - gap * 2.5, spot_ref - gap * 5, spot_ref - gap * 7.5,
        )

    calls_side = df_grouped[df_grouped['net_gex'] > 0].sort_values('net_gex', ascending=False)
    top_calls = calls_side['strike'].tolist()
    cw1 = top_calls[0] if len(top_calls) > 0 else spot_ref + gap * 2.5
    cw2 = top_calls[1] if len(top_calls) > 1 else cw1 + gap
    cw3 = top_calls[2] if len(top_calls) > 2 else cw2 + gap

    puts_side = df_grouped[df_grouped['net_gex'] < 0].sort_values('net_gex', ascending=True)
    top_puts = puts_side['strike'].tolist()
    pw1 = top_puts[0] if len(top_puts) > 0 else spot_ref - gap * 2.5
    pw2 = top_puts[1] if len(top_puts) > 1 else pw1 - gap
    pw3 = top_puts[2] if len(top_puts) > 2 else pw2 - gap

    return cw1, cw2, cw3, pw1, pw2, pw3


def compute_zero_crossing(df_by_strike: pd.DataFrame, value_col: str, spot_ref: float) -> float:
    """Strike donde la suma acumulada de 'value_col' (ordenado por strike)
    cruza cero -- generalización de compute_zero_gamma (antes hardcodeada a
    'net_gex') para reusar la misma lógica con 'net_chex' y sacar el Charm
    Zero de Aleks Rosme (ver domain/heatmap.py::compute_charm_trend_line),
    sin duplicar el cálculo."""
    if df_by_strike is None or df_by_strike.empty or value_col not in df_by_strike.columns:
        return spot_ref

    df_sorted = df_by_strike.sort_values('strike')
    cum_val = df_sorted[value_col].cumsum()
    idx = cum_val.abs().idxmin()
    return float(df_sorted.loc[idx, 'strike'])


def compute_zero_gamma(df_by_strike: pd.DataFrame, spot_ref: float) -> float:
    """Strike donde la suma acumulada de net_gex (ordenado por strike)
    cruza cero. Port de la lógica de zero_gamma en app.py (~línea 1576)."""
    return compute_zero_crossing(df_by_strike, 'net_gex', spot_ref)
