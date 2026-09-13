import pandas as pd

from app.domain.metrics import (
    compute_metrics_for_dte,
    find_exp_keys_by_date,
    get_nearest_dte_subset,
)


def _multi_exp_df():
    return pd.DataFrame({
        'strike': [95.0, 100.0, 95.0, 100.0],
        'exp_key': ['2026-09-10:0', '2026-09-10:0', '2026-09-17:7', '2026-09-17:7'],
        'exp_date': ['2026-09-10', '2026-09-10', '2026-09-17', '2026-09-17'],
        'dte': [0, 0, 7, 7],
        'net_gex': [5.0, -3.0, 8.0, -1.0],
        'call_gex': [5.0, 1.0, 8.0, 2.0],
        'put_gex': [0.0, -4.0, 0.0, -3.0],
        'openInterest_c': [100, 200, 150, 250],
        'openInterest_p': [50, 300, 60, 310],
        'net_dex': [1.0, 2.0, 1.5, 2.5],
        'net_tex': [-0.5, -0.6, -0.4, -0.7],
        'net_vex': [0.2, 0.3, 0.25, 0.35],
        'net_chex': [0.1, 0.2, 0.15, 0.25],
        'net_vanna': [0.05, 0.06, 0.07, 0.08],
        'iv_c': [0.20, 0.21, 0.22, 0.23],
        'iv_p': [0.19, 0.20, 0.21, 0.22],
    })


def test_get_nearest_dte_subset_picks_lowest_dte():
    df = _multi_exp_df()
    subset = get_nearest_dte_subset(df)
    assert (subset['exp_key'] == '2026-09-10:0').all()
    assert len(subset) == 2


def test_get_nearest_dte_subset_empty_passthrough():
    empty = pd.DataFrame()
    assert get_nearest_dte_subset(empty).empty
    assert get_nearest_dte_subset(None) is None


def test_find_exp_keys_by_date_exact_match():
    df = _multi_exp_df()
    keys = find_exp_keys_by_date(df, '2026-09-10')
    assert keys == ['2026-09-10:0']


def test_find_exp_keys_by_date_falls_back_to_next_future_date():
    df = _multi_exp_df()
    # no hay expiracion exacta en 09-12 -> debe caer en la siguiente (09-17)
    keys = find_exp_keys_by_date(df, '2026-09-12')
    assert keys == ['2026-09-17:7']


def test_find_exp_keys_by_date_no_match_returns_empty():
    df = _multi_exp_df()
    assert find_exp_keys_by_date(df, '2027-01-01') == []


def test_compute_metrics_for_dte_filters_and_aggregates():
    df = _multi_exp_df()
    metrics = compute_metrics_for_dte(df, ['2026-09-10:0'], spot_ref=100.0)
    # Solo la expiración 0DTE: net_gex_total = 5.0 + (-3.0) = 2.0
    assert abs(metrics['net_gex_total'] - 2.0) < 1e-9
    assert metrics['cw1'] == 95.0  # único strike con net_gex positivo en ese DTE
    assert metrics['pw1'] == 100.0
    # Gamma Wall: 95 (|5|+|0|=5) empata en total bruto con 100 (|1|+|4|=5) --
    # idxmax() de pandas devuelve el primer strike en caso de empate.
    assert metrics['dominant_wall'] == 95.0


def test_compute_metrics_for_dte_skew_put_call_near_atm():
    # Único strike dentro de la ventana ATM (+-2.5% de 100.0) para esa
    # expiración es 100.0 -- iv_c=0.21, iv_p=0.20 (ver _multi_exp_df).
    df = _multi_exp_df()
    metrics = compute_metrics_for_dte(df, ['2026-09-10:0'], spot_ref=100.0)
    assert abs(metrics['atm_iv_call'] - 0.21) < 1e-9
    assert abs(metrics['atm_iv_put'] - 0.20) < 1e-9
    assert abs(metrics['skew'] - (-0.01)) < 1e-9


def test_compute_metrics_for_dte_skew_none_when_no_near_atm_data():
    # spot_ref lejos de cualquier strike real -> ninguno entra en la
    # ventana ATM -> skew debe ser None, no 0.0 (0.0 se leería como "sin
    # skew" en vez de "sin datos").
    df = _multi_exp_df()
    metrics = compute_metrics_for_dte(df, ['2026-09-10:0'], spot_ref=1000.0)
    assert metrics['atm_iv_call'] is None
    assert metrics['atm_iv_put'] is None
    assert metrics['skew'] is None


def test_compute_metrics_for_dte_fallback_on_empty_selection():
    df = _multi_exp_df()
    metrics = compute_metrics_for_dte(df, ['no-existe:99'], spot_ref=200.0)
    assert metrics['zero_gamma'] == 200.0
    assert metrics['net_gex_total'] == 0.0


def test_compute_metrics_for_dte_fallback_on_empty_df():
    metrics = compute_metrics_for_dte(pd.DataFrame(), [], spot_ref=50.0)
    assert metrics['cw1'] == 55.0
    assert metrics['regime_str'] == 'neutral regime'
