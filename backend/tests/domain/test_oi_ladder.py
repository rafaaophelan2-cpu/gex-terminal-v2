import pandas as pd

from app.domain.oi_ladder import (
    build_oi_ladder,
    compute_atm_straddle,
    compute_flip_from_ladder,
    compute_net_gex_for_expiration,
    resolve_expiration_key,
)

MULTI_EXP_DF = pd.DataFrame([
    {"strike": 495.0, "exp_key": "e0", "dte": 0, "openInterest_c": 100, "openInterest_p": 40,
     "volume_c": 10, "volume_p": 5, "call_gex": 50.0, "put_gex": 0.0, "net_gex": 50.0,
     "mark_c": 1.2, "mark_p": 0.8},
    {"strike": 505.0, "exp_key": "e0", "dte": 0, "openInterest_c": 20, "openInterest_p": 200,
     "volume_c": 3, "volume_p": 40, "call_gex": 0.0, "put_gex": -30.0, "net_gex": -30.0,
     "mark_c": 0.7, "mark_p": 1.5},
    {"strike": 500.0, "exp_key": "e7", "dte": 7, "openInterest_c": 999, "openInterest_p": 999,
     "volume_c": 1, "volume_p": 1, "call_gex": 999.0, "put_gex": 0.0, "net_gex": 999.0,
     "mark_c": 5.0, "mark_p": 5.0},
])


def test_resolve_expiration_key_0dte_is_lowest_dte():
    assert resolve_expiration_key(MULTI_EXP_DF, "0dte") == "e0"


def test_resolve_expiration_key_next_is_second_lowest_dte():
    assert resolve_expiration_key(MULTI_EXP_DF, "next") == "e7"


def test_resolve_expiration_key_next_falls_back_to_0dte_when_only_one_expiration():
    df = MULTI_EXP_DF[MULTI_EXP_DF["exp_key"] == "e0"]
    assert resolve_expiration_key(df, "next") == "e0"


def test_resolve_expiration_key_none_for_empty_or_missing_columns():
    assert resolve_expiration_key(pd.DataFrame(), "0dte") is None
    assert resolve_expiration_key(pd.DataFrame([{"strike": 1.0}]), "0dte") is None


def test_build_oi_ladder_returns_call_and_put_oi_per_strike():
    ladder = build_oi_ladder(MULTI_EXP_DF, spot_price=500.0, expiration="0dte")
    assert {row["strike"] for row in ladder} == {495.0, 505.0}
    by_strike = {row["strike"]: row for row in ladder}
    assert by_strike[495.0]["call_oi"] == 100
    assert by_strike[495.0]["put_oi"] == 40
    assert by_strike[505.0]["call_oi"] == 20
    assert by_strike[505.0]["put_oi"] == 200
    assert by_strike[495.0]["call_volume"] == 10
    assert by_strike[505.0]["put_volume"] == 40


def test_build_oi_ladder_excludes_other_expirations():
    ladder = build_oi_ladder(MULTI_EXP_DF, spot_price=500.0, expiration="0dte")
    assert 500.0 not in {row["strike"] for row in ladder}  # e7, no e0


def test_build_oi_ladder_next_expiration_filter():
    ladder = build_oi_ladder(MULTI_EXP_DF, spot_price=500.0, expiration="next")
    assert {row["strike"] for row in ladder} == {500.0}
    assert ladder[0]["call_oi"] == 999


def test_build_oi_ladder_window_caps_at_n_strikes_around_atm():
    rows = [
        {"strike": float(s), "exp_key": "e0", "dte": 0, "net_gex": 1.0}
        for s in range(0, 100)
    ]
    df = pd.DataFrame(rows)
    ladder = build_oi_ladder(df, spot_price=50.0, expiration="0dte", n_strikes=5)
    strikes = sorted(row["strike"] for row in ladder)
    assert strikes == [45.0, 46.0, 47.0, 48.0, 49.0, 50.0, 51.0, 52.0, 53.0, 54.0, 55.0]


def test_build_oi_ladder_empty_for_no_data_or_invalid_spot():
    assert build_oi_ladder(pd.DataFrame(), spot_price=500.0) == []
    assert build_oi_ladder(MULTI_EXP_DF, spot_price=0.0) == []


def test_build_oi_ladder_next_falls_back_to_0dte_when_only_one_expiration():
    # Mismo fallback que resolve_expiration_key -- 'next' sin una segunda
    # expiración disponible no debe dejar la ladder vacía por un filtro
    # que no tiene ningún sentido pedir en ese momento.
    df = pd.DataFrame([{"strike": 1.0, "exp_key": "only", "dte": 0, "net_gex": 1.0}])
    ladder = build_oi_ladder(df, spot_price=1.0, expiration="next")
    assert [row["strike"] for row in ladder] == [1.0]


def test_compute_flip_from_ladder_reuses_zero_gamma_logic():
    ladder = build_oi_ladder(MULTI_EXP_DF, spot_price=500.0, expiration="0dte")
    # Flip por perfil de precio con el OI de la ladder (495: +60 neto de
    # calls, 505: -180 neto de puts) -- cruza entre los dos strikes, más
    # cerca de 495 porque del lado de 505 pesa el triple. Lo fino se prueba
    # en test_gex_math.py; acá solo el wiring (call_oi/put_oi -> OI).
    flip = compute_flip_from_ladder(ladder, 500.0)
    assert 495.0 < flip < 500.0


def test_compute_flip_from_ladder_is_none_when_empty():
    # Antes caía al spot, que se mostraba como si fuera un flip real.
    assert compute_flip_from_ladder([], 500.0) is None


def test_compute_net_gex_for_expiration_sums_only_that_expiration():
    assert compute_net_gex_for_expiration(MULTI_EXP_DF, "0dte") == 20.0  # 50 - 30
    assert compute_net_gex_for_expiration(MULTI_EXP_DF, "next") == 999.0


def test_compute_net_gex_for_expiration_zero_for_empty():
    assert compute_net_gex_for_expiration(pd.DataFrame(), "0dte") == 0.0


def test_compute_atm_straddle_uses_nearest_strike_marks():
    straddle = compute_atm_straddle(MULTI_EXP_DF, spot_price=498.0, expiration="0dte")
    assert straddle["strike"] == 495.0  # más cerca de 498 que 505
    assert straddle["call_mark"] == 1.2
    assert straddle["put_mark"] == 0.8
    assert straddle["straddle_price"] == 2.0


def test_compute_atm_straddle_none_without_mark_columns():
    df = MULTI_EXP_DF.drop(columns=["mark_c", "mark_p"])
    assert compute_atm_straddle(df, spot_price=500.0) is None


def test_compute_atm_straddle_none_for_empty_or_invalid_spot():
    assert compute_atm_straddle(pd.DataFrame(), spot_price=500.0) is None
    assert compute_atm_straddle(MULTI_EXP_DF, spot_price=0.0) is None
