import pandas as pd
import pytest

from app.domain.vol_surface import compute_vol_surface

DF = pd.DataFrame([
    # strike 95 < spot (100): OTM = put -> iv_p
    {"strike": 95.0, "exp_key": "2026-09-11:0", "exp_date": "2026-09-11", "dte": 0, "iv_c": 0.30, "iv_p": 0.35},
    # strike 105 >= spot: OTM = call -> iv_c
    {"strike": 105.0, "exp_key": "2026-09-11:0", "exp_date": "2026-09-11", "dte": 0, "iv_c": 0.28, "iv_p": 0.40},
    # strike 100 == spot (borde >= va a call), iv_c es 0 (sin cotización) -> cae a iv_p
    {"strike": 100.0, "exp_key": "2026-09-21:10", "exp_date": "2026-09-21", "dte": 10, "iv_c": 0.0, "iv_p": 0.22},
])


def test_compute_vol_surface_empty_when_no_exp_keys_selected():
    assert compute_vol_surface(DF, [], 100.0) == {"strikes": [], "columns": [], "values": []}


def test_compute_vol_surface_empty_input_df():
    assert compute_vol_surface(pd.DataFrame(), ["2026-09-11:0"], 100.0) == {"strikes": [], "columns": [], "values": []}


def test_compute_vol_surface_uses_otm_convention():
    grid = compute_vol_surface(DF, ["2026-09-11:0"], 100.0)

    assert grid["strikes"] == [95.0, 105.0]
    assert [c["exp_key"] for c in grid["columns"]] == ["2026-09-11:0"]

    row_95 = grid["values"][grid["strikes"].index(95.0)]
    row_105 = grid["values"][grid["strikes"].index(105.0)]
    assert row_95 == pytest.approx([35.0])  # put OTM, iv_p*100
    assert row_105 == pytest.approx([28.0])  # call OTM, iv_c*100


def test_compute_vol_surface_falls_back_when_otm_side_has_no_quote():
    grid = compute_vol_surface(DF, ["2026-09-21:10"], 100.0)
    row_100 = grid["values"][grid["strikes"].index(100.0)]
    assert row_100 == [22.0]  # iv_c==0 (sin cotización) -> cae a iv_p


def test_compute_vol_surface_missing_strike_in_expiration_is_none():
    grid = compute_vol_surface(DF, ["2026-09-11:0", "2026-09-21:10"], 100.0)
    assert grid["strikes"] == [95.0, 100.0, 105.0]

    row_95 = grid["values"][grid["strikes"].index(95.0)]
    # strike 95 solo existe en la expiración 0DTE -- la de 10DTE queda en
    # None (hueco), no en 0.0 (que sería un 0% de IV inventado).
    assert row_95 == [35.0, None]
