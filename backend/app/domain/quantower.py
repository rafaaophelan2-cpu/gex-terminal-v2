import pandas as pd

from app.domain.gex_math import compute_call_put_walls, compute_gamma_wall, compute_zero_gamma
from app.domain.metrics import get_nearest_dte_subset
from app.domain.oi_ladder import build_oi_ladder, compute_flip_for_expiration

DEFAULT_CONVERSION_RATIO = 41.125


def _level_or_zero(value: float | None) -> float:
    return float(value) if value is not None else 0.0


def _level_or_none(value: float | None) -> float | None:
    return float(value) if value is not None else None


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
    gamma_wall, levels: [{strike, net_gex}]} + 'oi_ladder' (campo nuevo,
    ver abajo). Port de la sección final de export_live_levels_to_quantower
    en app.py (~línea 1685): SIEMPRE la expiración más cercana (0DTE),
    nunca el DTE que cualquier conexión WS tenga seleccionado -- el feed
    de Quantower es compartido y determinístico, no depende de qué esté
    mirando cada usuario."""
    if df is None or df.empty or spot_price <= 0 or 'net_gex' not in df.columns:
        return None

    df_sel = get_nearest_dte_subset(df)
    if df_sel is None or df_sel.empty:
        return None

    # call_gex/put_gex se agregan solo si existen -- el mismo patrón
    # defensivo que ya usa domain/metrics.py (línea ~82) para el resto de
    # los consumidores de este DataFrame.
    agg_cols: dict[str, str] = {'net_gex': 'sum'}
    if 'call_gex' in df_sel.columns:
        agg_cols['call_gex'] = 'sum'
    if 'put_gex' in df_sel.columns:
        agg_cols['put_gex'] = 'sum'

    by_strike = df_sel.groupby('strike', as_index=False).agg(agg_cols).sort_values('strike')
    cw1, cw2, cw3, pw1, pw2, pw3 = compute_call_put_walls(by_strike, spot_price)
    gamma_wall = compute_gamma_wall(by_strike, spot_price)

    # zero_gamma: mismo flip que la web (compute_flip_for_expiration, ver
    # gex_info_payload en market_feed.py): cruce del perfil de precio de la
    # expiración más cercana, con toda su cadena. Si no hay open interest
    # (df sin esas columnas), cae al cruce de la acumulada sobre by_strike.
    oi_ladder = build_oi_ladder(df, spot_price, expiration='0dte')
    zero_gamma = compute_flip_for_expiration(df, spot_price, expiration='0dte')
    if zero_gamma is None and not {'openInterest_c', 'openInterest_p'}.issubset(df.columns):
        zero_gamma = compute_zero_gamma(by_strike, spot_price)

    return {
        "qqq_spot": float(spot_price),
        "conversion_ratio": float(conversion_ratio),
        # Un nivel que no existe va como 0.0, nunca como un número
        # inventado: GexProfileCloud.cs no dibuja niveles <= 0 (y un null
        # lo borraría Firebase igual, dejando el campo en 0 del lado C#).
        "cw1": _level_or_zero(cw1), "cw2": _level_or_zero(cw2), "cw3": _level_or_zero(cw3),
        "pw1": _level_or_zero(pw1), "pw2": _level_or_zero(pw2), "pw3": _level_or_zero(pw3),
        "zero_gamma": _level_or_zero(zero_gamma),
        "gamma_wall": _level_or_zero(gamma_wall),
        "levels": [
            {"strike": float(r.strike), "net_gex": float(r.net_gex)}
            for r in by_strike.itertuples()
        ],
        # Campo NUEVO, aditivo -- GexProfileCloud.cs (Quantower) no lo lee
        # todavía, no rompe nada del lado del indicador; disponible para
        # quien sí quiera consumir la ladder completa desde este mismo
        # nodo de Firebase (ver docstring arriba, "faltan estos cambios").
        "oi_ladder": oi_ladder,
    }


def build_eod_levels_from_snapshot(snapshot: dict | None) -> dict | None:
    """Recalcula CW1-3/PW1-3/Zero Gamma/Gamma Wall a partir de un snapshot
    YA guardado en Supabase (ver integrations/supabase_client.py::
    fetch_latest_snapshot) -- para GET /market/premarket-briefing, que
    necesita niveles del ÚLTIMO CIERRE conocido sin depender de que haya
    un SymbolFeed activo (nadie mirando el dashboard, como pasa de noche/
    pre-market) ni de ninguna fuente externa (InsiderFinance, Cboe).
    'snapshot' trae 'spot' y 'strikes': [{strike, call_gex, put_gex,
    net_gex}] -- mismo shape que guarda snapshot_writer.py cada 60s
    durante la sesión. None si no hay snapshot o le faltan campos."""
    if not snapshot or not snapshot.get('strikes') or float(snapshot.get('spot', 0.0)) <= 0:
        return None

    spot_price = float(snapshot['spot'])
    by_strike = pd.DataFrame(snapshot['strikes'])
    if 'call_gex' not in by_strike.columns or 'put_gex' not in by_strike.columns or 'net_gex' not in by_strike.columns:
        return None
    by_strike = by_strike.sort_values('strike')

    cw1, cw2, cw3, pw1, pw2, pw3 = compute_call_put_walls(by_strike, spot_price)
    zero_gamma = compute_zero_gamma(by_strike, spot_price)
    gamma_wall = compute_gamma_wall(by_strike, spot_price)

    return {
        "spot": spot_price,
        "cw1": _level_or_none(cw1), "cw2": _level_or_none(cw2), "cw3": _level_or_none(cw3),
        "pw1": _level_or_none(pw1), "pw2": _level_or_none(pw2), "pw3": _level_or_none(pw3),
        "zero_gamma": _level_or_none(zero_gamma),
        "gamma_wall": _level_or_none(gamma_wall),
        "atm_iv": float(snapshot.get('atm_iv', 0.0) or 0.0),
        "as_of_time": snapshot.get('time'),
    }
