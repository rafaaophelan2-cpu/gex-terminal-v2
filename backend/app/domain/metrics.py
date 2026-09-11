import numpy as np
import pandas as pd

from app.domain.gex_math import compute_call_put_walls, compute_zero_gamma

AGG_SUM_COLS = [
    'net_gex', 'call_gex', 'put_gex', 'openInterest_c', 'openInterest_p',
    'net_dex', 'call_dex', 'put_dex', 'net_tex', 'net_vex', 'net_chex', 'net_vanna',
]
AGG_MEAN_COLS = ['iv_c', 'iv_p']


def get_nearest_dte_subset(df_source: pd.DataFrame) -> pd.DataFrame:
    """Subconjunto de la expiración con menor DTE (0DTE cuando existe).
    Determinístico, para usar en feeds compartidos (snapshot_writer,
    quantower_pusher) que NUNCA deben depender de una selección de DTE por
    conexión/usuario. Port de get_nearest_dte_subset en app.py (~línea 1471)."""
    if df_source is None or df_source.empty:
        return df_source
    if 'exp_key' in df_source.columns and 'dte' in df_source.columns:
        nearest_key = df_source.sort_values('dte')['exp_key'].iloc[0]
        df_sel = df_source[df_source['exp_key'] == nearest_key]
        if not df_sel.empty:
            return df_sel
    return df_source


def find_exp_keys_by_date(df_source: pd.DataFrame, target_date_str: str) -> list[str]:
    """exp_keys cuya exp_date coincide con target_date_str, o la próxima
    fecha disponible si no hay coincidencia exacta. Port de
    find_exp_keys_by_date en app.py (~línea 2341)."""
    if df_source is None or df_source.empty or 'exp_date' not in df_source.columns:
        return []

    exact = df_source[df_source['exp_date'] == target_date_str]['exp_key'].unique().tolist()
    if exact:
        return exact

    future = df_source[df_source['exp_date'] > target_date_str]
    if not future.empty:
        nearest_date = future['exp_date'].min()
        return df_source[df_source['exp_date'] == nearest_date]['exp_key'].unique().tolist()

    return []


def _metrics_fallback(spot_ref: float) -> dict:
    return {
        "cw1": spot_ref + 5, "cw2": spot_ref + 10, "cw3": spot_ref + 15,
        "pw1": spot_ref - 5, "pw2": spot_ref - 10, "pw3": spot_ref - 15,
        "zero_gamma": spot_ref, "net_gex_total": 0.0, "call_gex_sum": 0.0, "put_gex_sum": 0.0,
        "net_dex_val": 0.0, "net_tex_val": 0.0, "net_vex_val": 0.0, "net_chex_val": 0.0, "net_vanna_val": 0.0,
        "iv_str": "20.00%", "iv_rank_str": "N/A", "regime_str": "neutral regime",
        "condition_str": "Neutral",
    }


def compute_metrics_for_dte(df_source: pd.DataFrame, exp_keys: list[str], spot_ref: float) -> dict:
    """Recalcula Walls/Zero Gamma/Net GEX/Griegas para un subconjunto de
    expiraciones (exp_keys). No vuelve a calcular Gamma/Delta desde cero:
    asume que df_source ya trae esas columnas (ver gex_math), solo filtra
    y reagrupa por strike. Port de compute_metrics_for_dte en app.py
    (~línea 2363)."""
    if df_source is None or df_source.empty or not exp_keys or 'exp_key' not in df_source.columns:
        return _metrics_fallback(spot_ref)

    df_sel = df_source[df_source['exp_key'].isin(exp_keys)].copy()
    if df_sel.empty:
        return _metrics_fallback(spot_ref)

    agg_map = {col: 'sum' for col in AGG_SUM_COLS if col in df_sel.columns}
    agg_map.update({col: 'mean' for col in AGG_MEAN_COLS if col in df_sel.columns})
    df_agg = df_sel.groupby('strike', as_index=False).agg(agg_map).sort_values('strike').reset_index(drop=True)

    cw1, cw2, cw3, pw1, pw2, pw3 = compute_call_put_walls(df_agg, spot_ref)
    zero_gamma = compute_zero_gamma(df_agg, spot_ref) if 'net_gex' in df_agg.columns else spot_ref

    net_gex_total = float(df_agg['net_gex'].sum()) if 'net_gex' in df_agg.columns else 0.0
    call_gex_sum = float(df_agg['call_gex'].sum()) if 'call_gex' in df_agg.columns else 0.0
    put_gex_sum = float(df_agg['put_gex'].sum()) if 'put_gex' in df_agg.columns else 0.0

    net_dex_val = float(df_agg['net_dex'].sum()) if 'net_dex' in df_agg.columns else 0.0
    net_tex_val = float(df_agg['net_tex'].sum()) if 'net_tex' in df_agg.columns else 0.0
    net_vex_val = float(df_agg['net_vex'].sum()) if 'net_vex' in df_agg.columns else 0.0
    net_chex_val = float(df_agg['net_chex'].sum()) if 'net_chex' in df_agg.columns else 0.0
    net_vanna_val = float(df_agg['net_vanna'].sum()) if 'net_vanna' in df_agg.columns else 0.0

    valid_ivs = []
    if spot_ref > 0:
        near_atm = df_agg[abs(df_agg['strike'] - spot_ref) <= (spot_ref * 0.025)]
        for _, r in near_atm.iterrows():
            iv_c = r.get('iv_c', 0)
            iv_p = r.get('iv_p', 0)
            if 0.02 < iv_c < 3.0:
                valid_ivs.append(iv_c)
            if 0.02 < iv_p < 3.0:
                valid_ivs.append(iv_p)
    atm_iv = float(np.median(valid_ivs)) if valid_ivs else 0.20

    regime_str = "positive regime" if net_gex_total >= 0 else "negative regime"
    condition_str = (
        "Positive – dealers long gamma, hedging dampens volatility (mean-reverting)"
        if net_gex_total >= 0 else
        "Negative – dealers short gamma, hedging amplifies trending behavior"
    )

    return {
        "cw1": cw1, "cw2": cw2, "cw3": cw3, "pw1": pw1, "pw2": pw2, "pw3": pw3,
        "zero_gamma": zero_gamma, "net_gex_total": net_gex_total,
        "call_gex_sum": call_gex_sum, "put_gex_sum": put_gex_sum,
        "net_dex_val": net_dex_val, "net_tex_val": net_tex_val, "net_vex_val": net_vex_val,
        "net_chex_val": net_chex_val, "net_vanna_val": net_vanna_val,
        "iv_str": f"{atm_iv * 100:.2f}%",
        "iv_rank_str": f"{int(min(max((atm_iv / 0.35) * 100, 15), 85))}th percentile",
        "regime_str": regime_str, "condition_str": condition_str,
    }
