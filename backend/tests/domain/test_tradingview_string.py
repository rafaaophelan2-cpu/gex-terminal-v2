import pandas as pd

from app.domain.tradingview_string import build_tradingview_levels_string, compute_dominant_gamma_wall


def test_compute_dominant_gamma_wall_picks_largest_magnitude():
    by_strike = pd.DataFrame([
        {"strike": 700.0, "net_gex": -500.0},
        {"strike": 705.0, "net_gex": -900000.0},
        {"strike": 720.0, "net_gex": 1450000.0},
    ])
    assert compute_dominant_gamma_wall(by_strike) == 720.0


def test_compute_dominant_gamma_wall_empty():
    assert compute_dominant_gamma_wall(pd.DataFrame()) is None


def test_build_tradingview_levels_string_matches_expected_format():
    walls = {"cw1": 720.0, "cw2": 725.0, "cw3": 730.0, "pw1": 718.0, "pw2": 710.0, "pw3": 715.0}
    result = build_tradingview_levels_string("QQQ", walls, zero_gamma=709.0, dominant_wall=705.0)
    assert result == (
        "$QQQ!: Call Wall 1, 720, Call Wall 2, 725, Call Wall 3, 730, "
        "Put Wall 1, 718, Put Wall 2, 710, Put Wall 3, 715, "
        "Gamma Flip, 709, Gamma Wall, 705."
    )


def test_build_tradingview_levels_string_strips_trailing_decimal_zeros():
    walls = {"cw1": 717.5, "cw2": 725.0, "cw3": 730.0, "pw1": 718.0, "pw2": 710.0, "pw3": 715.0}
    result = build_tradingview_levels_string("SPY", walls, zero_gamma=709.25, dominant_wall=705.0)
    assert "Call Wall 1, 717.5," in result
    assert "Gamma Flip, 709.25," in result
    assert result.startswith("$SPY!:")
