import pandas as pd

from app.domain.gex_math import compute_call_put_walls, compute_zero_gamma
from app.domain.metrics import get_nearest_dte_subset

DEFAULT_CONVERSION_RATIO = 41.125


def compute_conversion_ratio(nq_price: float, spot_price: float) -> float:
    """ratio = precio de NQ / spot del subyacente -- port de la fórmula
    en app.py (~línea 1377); si cualquiera de los dos no es válido, usa
    la misma constante de respaldo que usa app.py."""
    if nq_price > 0 and spot_price > 0:
        return nq_price / spot_price
    return DEFAULT_CONVERSION_RATIO


def build_live_levels_payload(df: pd.DataFrame, spot_price: float, conversion_ratio: float) -> dict | None:
    """Arma el payload exacto que espera GexProfileCloud.cs (indicador
    "Rafoph's Gex Manual 2.0" en Quantower) en el nodo /live_levels de
    Firebase: {qqq_spot, conversion_ratio, cw1..cw3, pw1..pw3, zero_gamma,
    levels: [{strike, net_gex}]}. Port de la sección final de
    export_live_levels_to_quantower en app.py (~línea 1685):
    SIEMPRE la expiración más cercana (0DTE), nunca el DTE que cualquier
    conexión WS tenga seleccionado -- el feed de Quantower es compartido
    y determinístico, no depende de qué esté mirando cada usuario."""
    if df is None or df.empty or spot_price <= 0 or 'net_gex' not in df.columns:
        return None

    df_sel = get_nearest_dte_subset(df)
    if df_sel is None or df_sel.empty:
        return None

    by_strike = df_sel.groupby('strike', as_index=False)['net_gex'].sum().sort_values('strike')
    cw1, cw2, cw3, pw1, pw2, pw3 = compute_call_put_walls(by_strike, spot_price)
    zero_gamma = compute_zero_gamma(by_strike, spot_price)

    return {
        "qqq_spot": float(spot_price),
        "conversion_ratio": float(conversion_ratio),
        "cw1": float(cw1), "cw2": float(cw2), "cw3": float(cw3),
        "pw1": float(pw1), "pw2": float(pw2), "pw3": float(pw3),
        "zero_gamma": float(zero_gamma),
        "levels": [
            {"strike": float(r.strike), "net_gex": float(r.net_gex)}
            for r in by_strike.itertuples()
        ],
    }
