import pandas as pd

from app.domain.quantower import build_live_levels_payload, compute_conversion_ratio


def test_compute_conversion_ratio_uses_live_prices():
    assert compute_conversion_ratio(nq_price=20000.0, spot_price=500.0) == 40.0


def test_compute_conversion_ratio_falls_back_when_invalid():
    assert compute_conversion_ratio(nq_price=0.0, spot_price=500.0) == 41.125
    assert compute_conversion_ratio(nq_price=20000.0, spot_price=0.0) == 41.125


def test_build_live_levels_payload_none_for_empty_or_invalid():
    assert build_live_levels_payload(pd.DataFrame(), 100.0, 41.125) is None
    df = pd.DataFrame([{"strike": 100.0, "net_gex": 1.0, "exp_key": "e0", "dte": 0}])
    assert build_live_levels_payload(df, 0.0, 41.125) is None


def test_build_live_levels_payload_matches_quantower_schema():
    df = pd.DataFrame([
        {"strike": 495.0, "net_gex": 50.0, "exp_key": "2026-09-11:0", "dte": 0},
        {"strike": 505.0, "net_gex": -30.0, "exp_key": "2026-09-11:0", "dte": 0},
        # Otra expiración: get_nearest_dte_subset debe excluirla del feed de Quantower.
        {"strike": 520.0, "net_gex": 999.0, "exp_key": "2026-09-18:7", "dte": 7},
    ])
    payload = build_live_levels_payload(df, spot_price=500.0, conversion_ratio=40.0)

    assert payload["qqq_spot"] == 500.0
    assert payload["conversion_ratio"] == 40.0
    assert set(payload.keys()) == {
        "qqq_spot", "conversion_ratio", "cw1", "cw2", "cw3", "pw1", "pw2", "pw3", "levels",
    }
    strikes_pushed = {lvl["strike"] for lvl in payload["levels"]}
    assert strikes_pushed == {495.0, 505.0}
    assert all(isinstance(lvl["net_gex"], float) for lvl in payload["levels"])
