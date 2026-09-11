import numpy as np
import pandas as pd


def compute_vol_surface(df: pd.DataFrame, exp_keys: list[str], spot: float) -> dict:
    """Superficie de volatilidad implícita (IV %) por strike x expiración,
    para 3D VOL SURFACE. Mismo shape de salida que compute_gamma_grid
    (strikes/columns/values) para reusar el mismo renderer Plotly Surface
    que 3D SURFACE (gamma_grid.py).

    Convención OTM: en strikes >= spot se usa la IV de las calls (fuera
    del dinero ahí) y en strikes < spot la de las puts -- las opciones
    OTM cotizan con más volumen y mejor bid-ask que las ITM profundas,
    así que su IV es la referencia estándar para construir una superficie
    de volatilidad (mismo criterio que usan los proveedores de datos de
    opciones, evita la IV ruidosa/estancada del lado ITM).

    A diferencia de compute_gamma_grid (celda sin datos = 0 USD de GEX,
    una lectura de dominio válida: sin open interest ahí, no hay
    exposición), acá una celda sin ese strike en esa expiración no tiene
    un "0% de IV" razonable -- se deja None, que Plotly.js interpreta
    como un hueco en la malla de la superficie en vez de hundirla a
    cero."""
    empty = {"strikes": [], "columns": [], "values": []}
    if df is None or df.empty or not exp_keys:
        return empty

    df_sel = df[df['exp_key'].isin(exp_keys)].copy()
    if df_sel.empty:
        return empty

    iv_c = df_sel['iv_c'].to_numpy(dtype=float)
    iv_p = df_sel['iv_p'].to_numpy(dtype=float)
    strikes_arr = df_sel['strike'].to_numpy(dtype=float)
    otm_is_call = strikes_arr >= spot
    iv_otm = np.where(
        otm_is_call,
        np.where(iv_c > 0, iv_c, iv_p),
        np.where(iv_p > 0, iv_p, iv_c),
    )
    df_sel['iv_otm'] = iv_otm * 100.0

    grouped = df_sel.groupby(['exp_key', 'strike'], as_index=False)['iv_otm'].mean()

    exp_info = df_sel[['exp_key', 'exp_date', 'dte']].drop_duplicates().sort_values('dte')
    columns = [
        {"exp_key": r.exp_key, "exp_date": r.exp_date, "dte": int(r.dte)}
        for r in exp_info.itertuples()
    ]
    col_index = {c['exp_key']: i for i, c in enumerate(columns)}

    strikes_sorted = sorted(grouped['strike'].unique().tolist())
    row_index = {s: i for i, s in enumerate(strikes_sorted)}

    values: list[list[float | None]] = [[None] * len(columns) for _ in strikes_sorted]
    for r in grouped.itertuples():
        values[row_index[r.strike]][col_index[r.exp_key]] = float(r.iv_otm)

    return {"strikes": strikes_sorted, "columns": columns, "values": values}
