import pandas as pd

from app.domain.gamma_price_profile import compute_gamma_price_profile


def _sample_chain():
    return pd.DataFrame([
        {"strike": 700.0, "openInterest_c": 500.0, "openInterest_p": 4000.0},
        {"strike": 710.0, "openInterest_c": 1500.0, "openInterest_p": 2000.0},
        {"strike": 720.0, "openInterest_c": 5000.0, "openInterest_p": 800.0},
        {"strike": 730.0, "openInterest_c": 3000.0, "openInterest_p": 300.0},
    ])


def test_empty_df_returns_empty_profile():
    result = compute_gamma_price_profile(pd.DataFrame(), 715.0, 1 / 365, 0.20)
    assert result == {"prices": [], "net_gamma": []}


def test_num_points_of_one_does_not_divide_by_zero():
    # Bug real: step = (hi - lo) / (num_points - 1) crashea con
    # ZeroDivisionError si num_points=1. Ningún caller actual pasa 1, pero
    # la función no tenía ningún resguardo propio contra eso.
    df = pd.DataFrame({'strike': [100.0], 'call_gex': [1.0], 'put_gex': [-1.0]})
    result = compute_gamma_price_profile(df, spot_ref=100.0, t_exp=0.01, iv=0.2, num_points=1)
    assert result == {"prices": [], "net_gamma": []}


def test_zero_spot_returns_empty_profile():
    result = compute_gamma_price_profile(_sample_chain(), 0.0, 1 / 365, 0.20)
    assert result == {"prices": [], "net_gamma": []}


def test_profile_spans_requested_range_and_point_count():
    result = compute_gamma_price_profile(_sample_chain(), 715.0, 1 / 365, 0.20, pct_range=0.1, num_points=21)
    assert len(result["prices"]) == 21
    assert len(result["net_gamma"]) == 21
    assert result["prices"][0] == round(715.0 * 0.9, 2)
    assert result["prices"][-1] == round(715.0 * 1.1, 2)


def test_profile_is_monotonic_ish_and_crosses_expected_sign_region():
    # Con más open interest de puts a la izquierda y de calls a la derecha
    # (ver _sample_chain), el gamma neto proyectado debería ser negativo
    # en precios bajos y positivo en precios altos -- la misma forma de
    # "S" que describe la curva de referencia del usuario.
    result = compute_gamma_price_profile(_sample_chain(), 715.0, 1 / 365, 0.20, pct_range=0.05, num_points=11)
    assert result["net_gamma"][0] < 0
    assert result["net_gamma"][-1] > 0


def test_default_range_follows_the_chain_instead_of_a_fixed_18_percent():
    # Auditoría 26-sep-2026: con ±18% fijo la curva de QQQ ocupaba ~15% del
    # ancho. Cadena 700-730 con spot 715: strikes a ±2.1%, más 3 desvíos de
    # 1 día al 20% (~3.1%) -> ~±5.2%, no ±18%.
    result = compute_gamma_price_profile(_sample_chain(), 715.0, 1 / 365, 0.20)
    lo, hi = result["prices"][0], result["prices"][-1]
    assert 715.0 * 0.93 < lo < 715.0 * 0.96
    assert 715.0 * 1.04 < hi < 715.0 * 1.07
    # En los bordes el gamma ya se apagó: la curva no queda cortada.
    peak = max(abs(v) for v in result["net_gamma"])
    assert abs(result["net_gamma"][0]) < 0.05 * peak
    assert abs(result["net_gamma"][-1]) < 0.05 * peak


def test_default_range_is_capped_for_very_wide_chains():
    vix = pd.DataFrame([
        {"strike": k, "openInterest_c": 100.0, "openInterest_p": 100.0}
        for k in (10.0, 12.0, 14.0, 16.0, 20.0, 25.0, 30.0)
    ])
    result = compute_gamma_price_profile(vix, 16.0, 1 / 365, 0.80)
    assert result["prices"][0] == round(16.0 * 0.82, 2)
    assert result["prices"][-1] == round(16.0 * 1.18, 2)
