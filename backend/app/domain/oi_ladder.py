import pandas as pd

from app.domain.gex_math import compute_zero_gamma

# Columnas que se agregan por strike cuando existen -- mismo patrón
# defensivo que metrics.py/quantower.py: un DataFrame viejo o de un feed
# sin alguna de estas columnas (ej. sin volume_c/volume_p) no debe romper
# la ladder, solo faltar esa parte del payload.
LADDER_AGG_COLS = ['openInterest_c', 'openInterest_p', 'volume_c', 'volume_p', 'call_gex', 'put_gex', 'net_gex']

DEFAULT_LADDER_STRIKES = 15


def resolve_expiration_key(df: pd.DataFrame, expiration: str) -> str | None:
    """Traduce el filtro 'expiration' ('0dte'|'next') al exp_key real de
    'df' -- '0dte' es la expiración con menor DTE (mismo criterio que
    get_nearest_dte_subset en metrics.py), 'next' es la SIGUIENTE
    expiración distinta en orden de DTE ascendente. Un valor de
    'expiration' desconocido, o 'next' cuando solo hay una expiración
    disponible, cae al mismo criterio que '0dte' -- nunca deja a quien
    llama sin ladder por un typo o por falta de una segunda expiración."""
    if df is None or df.empty or 'exp_key' not in df.columns or 'dte' not in df.columns:
        return None

    order = df[['exp_key', 'dte']].drop_duplicates().sort_values('dte').reset_index(drop=True)
    if order.empty:
        return None

    if expiration == 'next' and len(order) > 1:
        return str(order['exp_key'].iloc[1])
    return str(order['exp_key'].iloc[0])


def build_oi_ladder(df: pd.DataFrame, spot_price: float, expiration: str = '0dte', n_strikes: int = DEFAULT_LADDER_STRIKES) -> list[dict]:
    """Ladder de ±n_strikes strikes reales alrededor del strike más
    cercano al spot, para la expiración elegida (0DTE o próxima) -- con
    Open Interest y volumen de calls/puts por separado, además del gamma
    ya agregado.

    A diferencia de 'by_strike' en gex_info_payload (que se recorta al
    strike_range que cada usuario eligió ver en pantalla, una ventana que
    varía por conexión), esta ventana es SIEMPRE fija y determinística en
    ±n_strikes strikes reales alrededor del ATM -- pensada como fuente
    única para el flip (ver compute_flip_from_ladder abajo), que no debe
    depender de qué tan zoomeado esté el gráfico de barras de nadie."""
    if df is None or df.empty or spot_price <= 0:
        return []

    exp_key = resolve_expiration_key(df, expiration)
    if exp_key is None:
        return []

    df_exp = df[df['exp_key'] == exp_key]
    if df_exp.empty:
        return []

    agg_map = {col: 'sum' for col in LADDER_AGG_COLS if col in df_exp.columns}
    if not agg_map:
        return []

    by_strike = df_exp.groupby('strike', as_index=False).agg(agg_map).sort_values('strike').reset_index(drop=True)
    if by_strike.empty:
        return []

    atm_idx = int((by_strike['strike'] - spot_price).abs().idxmin())
    lo = max(0, atm_idx - n_strikes)
    hi = min(len(by_strike), atm_idx + n_strikes + 1)
    window = by_strike.iloc[lo:hi]

    return [
        {
            "strike": float(r.strike),
            "call_oi": int(r.openInterest_c) if 'openInterest_c' in agg_map else 0,
            "put_oi": int(r.openInterest_p) if 'openInterest_p' in agg_map else 0,
            "call_volume": int(r.volume_c) if 'volume_c' in agg_map else 0,
            "put_volume": int(r.volume_p) if 'volume_p' in agg_map else 0,
            "call_gex": float(r.call_gex) if 'call_gex' in agg_map else 0.0,
            "put_gex": float(r.put_gex) if 'put_gex' in agg_map else 0.0,
            "net_gex": float(r.net_gex) if 'net_gex' in agg_map else 0.0,
        }
        for r in window.itertuples()
    ]


def compute_flip_from_ladder(ladder: list[dict], spot_price: float) -> float:
    """Zero Gamma/flip calculado SOLO con los strikes de la ladder (ver
    build_oi_ladder), reusando compute_zero_gamma tal cual -- reemplaza
    el cálculo anterior, que corría sobre 'by_strike' potencialmente
    recortado al strike_range visible en pantalla (ventana variable por
    conexión, nunca pensada como fuente de un nivel real). Con la ladder
    vacía (sin feed todavía, o expiración sin datos) cae al spot, mismo
    fallback que compute_zero_gamma."""
    if not ladder:
        return spot_price
    return compute_zero_gamma(pd.DataFrame(ladder), spot_price)


def compute_net_gex_for_expiration(df: pd.DataFrame, expiration: str = '0dte') -> float:
    """Net GEX total (todos los strikes, no solo la ladder) de la
    expiración elegida -- usado para comparar contra el Net GEX de
    apertura en GET /market/zero-dte-snapshot."""
    if df is None or df.empty or 'net_gex' not in df.columns:
        return 0.0
    exp_key = resolve_expiration_key(df, expiration)
    if exp_key is None:
        return 0.0
    return float(df.loc[df['exp_key'] == exp_key, 'net_gex'].sum())


def compute_atm_straddle(df: pd.DataFrame, spot_price: float, expiration: str = '0dte') -> dict | None:
    """Precio del straddle ATM (call mark + put mark reales de Schwab en
    el strike más cercano al spot) para la expiración elegida. None si no
    hay datos de mark_c/mark_p (chain vieja, o feed sin esas columnas
    todavía) en vez de un precio inventado."""
    if df is None or df.empty or spot_price <= 0:
        return None

    exp_key = resolve_expiration_key(df, expiration)
    if exp_key is None:
        return None

    df_exp = df[df['exp_key'] == exp_key]
    if df_exp.empty or 'mark_c' not in df_exp.columns or 'mark_p' not in df_exp.columns:
        return None

    # 'max' y no 'sum': mark es un PRECIO, no una cantidad -- mismo
    # criterio que snapshot_writer.py para estas dos columnas.
    by_strike = df_exp.groupby('strike', as_index=False).agg({'mark_c': 'max', 'mark_p': 'max'}).sort_values('strike').reset_index(drop=True)
    if by_strike.empty:
        return None

    idx = int((by_strike['strike'] - spot_price).abs().idxmin())
    row = by_strike.iloc[idx]
    call_mark = float(row['mark_c'])
    put_mark = float(row['mark_p'])
    return {
        "strike": float(row['strike']),
        "call_mark": call_mark,
        "put_mark": put_mark,
        "straddle_price": call_mark + put_mark,
    }
