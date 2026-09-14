import pandas as pd
import pytest

from app.domain.gex_math import (
    compute_call_put_walls,
    compute_greeks_exposures,
    compute_zero_crossing,
    compute_zero_gamma,
    recalculate_gex_for_spot,
)


def _sample_df():
    return pd.DataFrame({
        'strike': [95.0, 100.0, 105.0],
        'openInterest_c': [100, 500, 50],
        'openInterest_p': [50, 300, 100],
        'delta_c': [0.80, 0.50, 0.20],
        'delta_p': [-0.20, -0.50, -0.80],
        'theta_c': [-0.10, -0.20, -0.08],
        'theta_p': [-0.09, -0.19, -0.07],
        'vega_c': [0.20, 0.30, 0.15],
        'vega_p': [0.18, 0.29, 0.14],
    })


def test_recalculate_gex_gamma_peaks_atm():
    df = recalculate_gex_for_spot(_sample_df(), spot_t=100.0, t_exp=7 / 365, iv=0.20)
    gamma_by_strike = df.set_index('strike')['gamma']
    # Propiedad conocida de Black-Scholes: la gamma es máxima cerca del ATM
    assert gamma_by_strike[100.0] > gamma_by_strike[95.0]
    assert gamma_by_strike[100.0] > gamma_by_strike[105.0]


def test_recalculate_gex_call_positive_put_negative():
    df = recalculate_gex_for_spot(_sample_df(), spot_t=100.0, t_exp=7 / 365, iv=0.20)
    assert (df['call_gex'] >= 0).all()
    assert (df['put_gex'] <= 0).all()
    assert (df['net_gex'] == df['call_gex'] + df['put_gex']).all()


def test_recalculate_gex_empty_or_invalid_spot():
    empty = pd.DataFrame()
    assert recalculate_gex_for_spot(empty, 100.0, 0.02, 0.2).empty
    df = _sample_df()
    result = recalculate_gex_for_spot(df, spot_t=0.0, t_exp=0.02, iv=0.2)
    assert result is df  # devuelve el input sin tocar si spot <= 0


def test_compute_greeks_exposures_net_dex_matches_manual_calc():
    df = compute_greeks_exposures(_sample_df(), spot_price=100.0, t_exp=7 / 365, atm_iv=0.20)
    row100 = df[df['strike'] == 100.0].iloc[0]
    expected_call_dex = 0.50 * 500 * 100 * 100.0 / 1e6
    expected_put_dex = -0.50 * 300 * 100 * 100.0 / 1e6
    assert abs(row100['call_dex'] - expected_call_dex) < 1e-9
    assert abs(row100['net_dex'] - (expected_call_dex + expected_put_dex)) < 1e-9


def test_compute_call_put_walls_ranks_by_magnitude():
    df_grouped = pd.DataFrame({
        'strike': [95.0, 100.0, 105.0, 110.0],
        'net_gex': [8.0, 3.0, -2.0, -9.0],
    })
    cw1, cw2, cw3, pw1, pw2, pw3 = compute_call_put_walls(df_grouped, spot_ref=100.0)
    assert cw1 == 95.0  # mayor net_gex positivo
    assert cw2 == 100.0
    assert pw1 == 110.0  # net_gex más negativo
    assert pw2 == 105.0


def test_compute_call_put_walls_empty_uses_fallback():
    cw1, cw2, cw3, pw1, pw2, pw3 = compute_call_put_walls(pd.DataFrame(), spot_ref=100.0)
    assert cw1 > 100.0
    assert pw1 < 100.0


def test_compute_call_put_walls_partial_fallback_uses_same_spacing_as_empty_fallback():
    # Bug real: con un solo strike real de cada lado, cw2/cw3 y pw2/pw3
    # sintéticos usaban un espaciado (+gap fijo encadenado) DISTINTO al
    # del fallback "sin ningún dato" (gap*2.5 por nivel desde spot_ref) --
    # dos convenciones distintas para la misma situación de fondo (no hay
    # wall real). Ahora ambos casos usan gap*2.5 por nivel, consistente.
    df_grouped = pd.DataFrame({'strike': [95.0, 105.0], 'net_gex': [8.0, -9.0]})
    cw1, cw2, cw3, pw1, pw2, pw3 = compute_call_put_walls(df_grouped, spot_ref=100.0, gap=2.0)
    assert cw1 == 95.0  # real
    assert cw2 == pytest.approx(95.0 + 2.0 * 2.5)
    assert cw3 == pytest.approx(95.0 + 2.0 * 5.0)
    assert pw1 == 105.0  # real
    assert pw2 == pytest.approx(105.0 - 2.0 * 2.5)
    assert pw3 == pytest.approx(105.0 - 2.0 * 5.0)


def test_compute_zero_gamma_crossing():
    df = pd.DataFrame({
        'strike': [95.0, 100.0, 105.0],
        'net_gex': [5.0, -3.0, -10.0],
    })
    # cumsum por strike: 5, 2, -8 -> el mínimo absoluto está en strike 100
    zg = compute_zero_gamma(df, spot_ref=100.0)
    assert zg == 100.0


def test_compute_zero_gamma_empty_uses_spot_fallback():
    assert compute_zero_gamma(pd.DataFrame(), spot_ref=123.45) == 123.45


def test_compute_zero_crossing_is_generic_over_value_col():
    # Misma matemática que compute_zero_gamma, pero con una columna
    # distinta (net_chex) -- confirma que la generalización (usada para
    # el Charm Zero de la línea de tendencia) da el mismo resultado que
    # daría compute_zero_gamma con esos mismos números.
    df = pd.DataFrame({
        'strike': [95.0, 100.0, 105.0],
        'net_chex': [5.0, -3.0, -10.0],
    })
    assert compute_zero_crossing(df, 'net_chex', spot_ref=100.0) == 100.0


def test_compute_zero_crossing_missing_column_uses_spot_fallback():
    df = pd.DataFrame({'strike': [95.0, 100.0], 'net_gex': [1.0, -1.0]})
    assert compute_zero_crossing(df, 'net_chex', spot_ref=42.0) == 42.0
