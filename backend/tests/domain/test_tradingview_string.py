import pandas as pd

from app.domain.tradingview_string import build_tradingview_levels_string, compute_dominant_gamma_wall


def test_compute_dominant_gamma_wall_picks_largest_total_magnitude():
    by_strike = pd.DataFrame([
        {"strike": 700.0, "call_gex": 200.0, "put_gex": -300.0, "net_gex": -100.0},
        {"strike": 705.0, "call_gex": 400000.0, "put_gex": -500000.0, "net_gex": -100000.0},
        {"strike": 720.0, "call_gex": 1450000.0, "put_gex": -100.0, "net_gex": 1449900.0},
    ])
    assert compute_dominant_gamma_wall(by_strike) == 720.0


def test_compute_dominant_gamma_wall_prefers_total_over_net():
    # 710 tiene MUCHO call Y put gex que casi se cancelan (net chico) --
    # el total bruto ahí (900k) supera al de 720 (200k neto y bruto,
    # solo del lado call), aunque el net_gex de 710 sea mucho más chico.
    by_strike = pd.DataFrame([
        {"strike": 710.0, "call_gex": 450000.0, "put_gex": -450000.0, "net_gex": 0.0},
        {"strike": 720.0, "call_gex": 200000.0, "put_gex": 0.0, "net_gex": 200000.0},
    ])
    assert compute_dominant_gamma_wall(by_strike) == 710.0


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


def test_build_tradingview_levels_string_omits_nan_wall_instead_of_literal_nan():
    # Bug real: 'value is not None' no excluye NaN -- un wall NaN (dato
    # corrupto río arriba) se colaba y salía como el string literal "nan"
    # dentro del texto que consume el indicador de Pine Script.
    walls = {"cw1": float("nan"), "cw2": 725.0, "cw3": 730.0, "pw1": 718.0, "pw2": 710.0, "pw3": 715.0}
    result = build_tradingview_levels_string("QQQ", walls, zero_gamma=709.0, dominant_wall=705.0)
    assert "nan" not in result.lower()
    assert "Call Wall 1" not in result
