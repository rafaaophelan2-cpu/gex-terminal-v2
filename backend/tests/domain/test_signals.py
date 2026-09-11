import json

import pandas as pd
import pytest

from app.domain.signals import compute_signals, compute_squeeze_screener

SPOT = 715.50

# Strikes cerca del spot con distinta magnitud de net_gex -- diseñado
# para que cada señal tenga un candidato claro y no ambiguo:
#   715.0 -> el strike |net_gex| más grande cerca del spot -> Magnet
#   716.0 -> primer strike positivo por encima del spot -> Resistance
#   700.0 -> put wall, bien por debajo -> Volatility (aumenta debajo)
BY_STRIKE = pd.DataFrame([
    {"strike": 700.0, "net_gex": -8_000_000.0, "call_gex": 1_000_000.0, "put_gex": -9_000_000.0,
     "openInterest_c": 500, "openInterest_p": 4000, "volume_c": 100, "volume_p": 900, "net_dex": -50_000.0},
    {"strike": 710.0, "net_gex": 3_000_000.0, "call_gex": 4_000_000.0, "put_gex": -1_000_000.0,
     "openInterest_c": 1000, "openInterest_p": 300, "volume_c": 200, "volume_p": 50, "net_dex": 20_000.0},
    {"strike": 715.0, "net_gex": 10_000_000.0, "call_gex": 11_000_000.0, "put_gex": -1_000_000.0,
     "openInterest_c": 3000, "openInterest_p": 500, "volume_c": 1500, "volume_p": 100, "net_dex": 80_000.0},
    {"strike": 716.0, "net_gex": 2_000_000.0, "call_gex": 2_500_000.0, "put_gex": -500_000.0,
     "openInterest_c": 800, "openInterest_p": 200, "volume_c": 300, "volume_p": 40, "net_dex": 15_000.0},
    {"strike": 720.0, "net_gex": 6_000_000.0, "call_gex": 6_500_000.0, "put_gex": -500_000.0,
     "openInterest_c": 2000, "openInterest_p": 100, "volume_c": 1200, "volume_p": 30, "net_dex": 60_000.0},
])

WALLS = {"cw1": 720.0, "cw2": 725.0, "cw3": 730.0, "pw1": 700.0, "pw2": 695.0, "pw3": 690.0, "zero_gamma": 705.0}


def test_compute_signals_empty_input():
    assert compute_signals(pd.DataFrame(), SPOT, WALLS) == []
    assert compute_signals(BY_STRIKE, 0.0, WALLS) == []


def test_compute_signals_returns_four_cards_in_order():
    signals = compute_signals(BY_STRIKE, SPOT, WALLS)
    types = [s["type"] for s in signals]
    assert types == ["volatility_dampened", "magnet", "resistance", "volatility_increased_below"]


def test_volatility_signal_reflects_positive_regime_at_spot():
    signals = compute_signals(BY_STRIKE, SPOT, WALLS)
    vol = signals[0]
    assert vol["level"] == SPOT
    assert vol["pct_from_spot"] == 0.0
    assert vol["badge"] in ("STRONG", "MODERATE")


def test_volatility_signal_flips_when_regime_is_negative():
    negative_df = BY_STRIKE.copy()
    negative_df['net_gex'] = -negative_df['net_gex']
    signals = compute_signals(negative_df, SPOT, WALLS)
    assert signals[0]["type"] == "volatility_increased"


def test_magnet_picks_strongest_strike_near_spot():
    signals = compute_signals(BY_STRIKE, SPOT, WALLS)
    magnet = next(s for s in signals if s["type"] == "magnet")
    assert magnet["level"] == 715.0
    assert magnet["badge"] == "STRONG"  # es el máximo |net_gex| de todo el set


def test_resistance_picks_nearest_positive_strike_above_spot():
    signals = compute_signals(BY_STRIKE, SPOT, WALLS)
    resistance = next(s for s in signals if s["type"] == "resistance")
    assert resistance["level"] == 716.0
    assert resistance["pct_from_spot"] > 0


def test_volatility_below_picks_the_closer_of_put_wall_and_zero_gamma():
    signals = compute_signals(BY_STRIKE, SPOT, WALLS)
    below = next(s for s in signals if s["type"] == "volatility_increased_below")
    # zero_gamma (705.0) está más cerca del spot que pw1 (700.0) -> gana
    assert below["level"] == 705.0
    assert below["pct_from_spot"] < 0


def test_compute_squeeze_screener_empty_input():
    empty = compute_squeeze_screener(pd.DataFrame(), SPOT, WALLS, 0.0)
    assert empty["probability"] is None
    assert compute_squeeze_screener(BY_STRIKE, SPOT, {}, 0.0)["probability"] is None


def test_compute_squeeze_screener_factors_sum_to_probability():
    result = compute_squeeze_screener(BY_STRIKE, SPOT, WALLS, net_dex_total=80_000.0)
    assert result["direction"] == "Bullish Squeeze"
    factor_sum = sum(f["score"] for f in result["factors"])
    assert result["probability"] == pytest.approx(factor_sum, abs=1)


def test_compute_squeeze_screener_trigger_level_matches_resistance_signal():
    result = compute_squeeze_screener(BY_STRIKE, SPOT, WALLS, net_dex_total=80_000.0)
    signals = compute_signals(BY_STRIKE, SPOT, WALLS)
    resistance = next(s for s in signals if s["type"] == "resistance")
    assert result["key_levels"]["trigger_level"] == resistance["level"]


def test_compute_squeeze_screener_call_wall_proximity_maxed_when_spot_above_wall():
    result = compute_squeeze_screener(BY_STRIKE, spot=725.0, walls=WALLS, net_dex_total=0.0)
    cw_factor = next(f for f in result["factors"] if f["label"] == "Call Wall Proximity")
    assert cw_factor["score"] == 25


def test_compute_squeeze_screener_gamma_regime_zero_when_positive():
    positive_df = BY_STRIKE.copy()  # ya es net positivo en conjunto
    result = compute_squeeze_screener(positive_df, SPOT, WALLS, net_dex_total=0.0)
    regime_factor = next(f for f in result["factors"] if f["label"] == "Gamma Regime")
    assert regime_factor["score"] == 0


def test_compute_signals_is_json_serializable():
    # Regresión real: 'level'/'pct_from_spot' de Magnet y Resistance salían
    # de un valor de pandas (numpy.float64) sin pasar por float() -- una
    # comparación == contra un float nativo en un test (ej. `level == 716.0`)
    # pasa igual sin importar el tipo real, así que ese bug NO lo agarraba
    # ningún assert de valor, solo se vio en producción: json.dumps (lo que
    # usa websocket.send_json) tira TypeError con numpy.float64, matando el
    # _tick_sender en silencio para siempre. Este test falla si vuelve a
    # colarse un tipo no nativo en cualquier campo.
    signals = compute_signals(BY_STRIKE, SPOT, WALLS)
    assert len(signals) > 0
    json.dumps(signals)
    for signal in signals:
        assert isinstance(signal["level"], float)
        assert isinstance(signal["pct_from_spot"], float)


def test_compute_squeeze_screener_is_json_serializable():
    result = compute_squeeze_screener(BY_STRIKE, SPOT, WALLS, net_dex_total=80_000.0)
    json.dumps(result)
    assert isinstance(result["probability"], int)
    for factor in result["factors"]:
        assert isinstance(factor["score"], int)
    for value in result["key_levels"].values():
        assert isinstance(value, float)
