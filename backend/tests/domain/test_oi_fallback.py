import pandas as pd

from app.domain.oi_fallback import apply_volume_fallback_if_no_oi


def test_keeps_real_oi_when_present():
    df = pd.DataFrame([
        {"strike": 700.0, "openInterest_c": 100, "openInterest_p": 50, "volume_c": 5, "volume_p": 2},
        {"strike": 705.0, "openInterest_c": 0, "openInterest_p": 0, "volume_c": 1, "volume_p": 1},
    ])
    out, used_fallback = apply_volume_fallback_if_no_oi(df)
    assert used_fallback is False
    assert out["openInterest_c"].tolist() == [100, 0]
    assert out["openInterest_p"].tolist() == [50, 0]


def test_substitutes_volume_when_oi_totally_zero():
    df = pd.DataFrame([
        {"strike": 29300.0, "openInterest_c": 0, "openInterest_p": 0, "volume_c": 2, "volume_p": 6},
        {"strike": 29400.0, "openInterest_c": 0, "openInterest_p": 0, "volume_c": 7, "volume_p": 46},
    ])
    out, used_fallback = apply_volume_fallback_if_no_oi(df)
    assert used_fallback is True
    assert out["openInterest_c"].tolist() == [2, 7]
    assert out["openInterest_p"].tolist() == [6, 46]


def test_empty_df_passthrough():
    df = pd.DataFrame()
    out, used_fallback = apply_volume_fallback_if_no_oi(df)
    assert out.empty
    assert used_fallback is False


def test_missing_oi_columns_passthrough():
    df = pd.DataFrame([{"strike": 700.0}])
    out, used_fallback = apply_volume_fallback_if_no_oi(df)
    assert used_fallback is False
    assert "openInterest_c" not in out.columns


def test_missing_volume_columns_no_fallback_even_if_oi_zero():
    df = pd.DataFrame([{"strike": 700.0, "openInterest_c": 0, "openInterest_p": 0}])
    out, used_fallback = apply_volume_fallback_if_no_oi(df)
    assert used_fallback is False
    assert out["openInterest_c"].tolist() == [0]


def test_does_not_mutate_input_df():
    df = pd.DataFrame([{"strike": 700.0, "openInterest_c": 0, "openInterest_p": 0, "volume_c": 3, "volume_p": 4}])
    out, used_fallback = apply_volume_fallback_if_no_oi(df)
    assert used_fallback is True
    assert df["openInterest_c"].tolist() == [0]  # original intacto
    assert out["openInterest_c"].tolist() == [3]
