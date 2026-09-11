import math

import pandas as pd


def list_expirations(df: pd.DataFrame) -> list[dict]:
    """Expiraciones disponibles en 'df' (cualquier DTE, no solo la más
    cercana) -- alimenta el selector de DTEs del GRID, mismo criterio de
    agrupación que render_dte_selector en app.py (~línea 2156): una fila
    por exp_key con su fecha, DTE y Net GEX total de esa expiración."""
    if df is None or df.empty or 'exp_key' not in df.columns:
        return []

    out = []
    for exp_key, group in df.groupby('exp_key'):
        exp_date = group['exp_date'].iloc[0] if 'exp_date' in group.columns else exp_key.split(':')[0]
        dte = int(group['dte'].iloc[0]) if 'dte' in group.columns else 0
        net_gex = float(group['net_gex'].sum()) if 'net_gex' in group.columns else 0.0
        out.append({"exp_key": exp_key, "exp_date": exp_date, "dte": dte, "net_gex": net_gex})

    return sorted(out, key=lambda x: x['dte'])


def compute_gamma_grid(df: pd.DataFrame, exp_keys: list[str]) -> dict:
    """Grid de Net GEX por strike x expiración -- a diferencia de GEX INFO
    (que solo muestra la expiración 0DTE/más cercana), esto arma una
    columna por cada expiración seleccionada, cada celda con el Net GEX
    real de ese strike en esa expiración específica.

    Cada celda trae, además del monto real en USD ('values', lo que se
    muestra como texto), un peso normalizado para el color ('weights'):
    el gamma de una opción escala aproximadamente con 1/sqrt(T) en
    Black-Scholes (a más tiempo al vencimiento, menos gamma por dólar de
    exposición nominal) -- así que la misma cantidad de USD en una
    expiración lejana representa gamma real menos concentrado/urgente
    para el hedging de dealers que en una cercana. Sin este ajuste, un
    nivel de 10M USD a 10DTE se vería en el mapa de color tan "fuerte"
    como 10M a 0DTE, cuando en la práctica el de 0DTE pesa mucho más en
    el hedging inmediato. weight = net_gex / sqrt(1 + dte)."""
    if df is None or df.empty or not exp_keys:
        return {"strikes": [], "columns": [], "values": [], "weights": [], "net_by_column": [], "max_abs_weight": 1.0}

    df_sel = df[df['exp_key'].isin(exp_keys)].copy()
    if df_sel.empty:
        return {"strikes": [], "columns": [], "values": [], "weights": [], "net_by_column": [], "max_abs_weight": 1.0}

    grouped = df_sel.groupby(['exp_key', 'strike'], as_index=False)['net_gex'].sum()

    exp_info = df_sel[['exp_key', 'exp_date', 'dte']].drop_duplicates().sort_values('dte')
    columns = [
        {"exp_key": r.exp_key, "exp_date": r.exp_date, "dte": int(r.dte)}
        for r in exp_info.itertuples()
    ]
    col_index = {c['exp_key']: i for i, c in enumerate(columns)}

    strikes_sorted = sorted(grouped['strike'].unique().tolist())
    row_index = {s: i for i, s in enumerate(strikes_sorted)}

    values = [[0.0] * len(columns) for _ in strikes_sorted]
    weights = [[0.0] * len(columns) for _ in strikes_sorted]

    for r in grouped.itertuples():
        row = row_index[r.strike]
        col = col_index[r.exp_key]
        dte = columns[col]['dte']
        net_gex = float(r.net_gex)
        values[row][col] = net_gex
        weights[row][col] = net_gex / math.sqrt(1 + dte)

    net_by_column = [0.0] * len(columns)
    for row in values:
        for j, v in enumerate(row):
            net_by_column[j] += v

    max_abs_weight = max((abs(w) for row in weights for w in row), default=0.0) or 1.0

    return {
        "strikes": strikes_sorted,
        "columns": columns,
        "values": values,
        "weights": weights,
        "net_by_column": net_by_column,
        "max_abs_weight": max_abs_weight,
    }
