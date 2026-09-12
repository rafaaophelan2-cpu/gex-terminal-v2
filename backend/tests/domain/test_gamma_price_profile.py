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
