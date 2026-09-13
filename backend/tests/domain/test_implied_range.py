import math

from app.domain.implied_range import compute_implied_range


def test_compute_implied_range_basic():
    result = compute_implied_range(spot=100.0, atm_iv=0.20, dte=1.0)
    expected_move = 100.0 * 0.20 * math.sqrt(1.0 / 365.0)
    assert result["expected_move"] == expected_move
    assert result["one_sd"]["low"] == 100.0 - expected_move
    assert result["one_sd"]["high"] == 100.0 + expected_move
    assert result["two_sd"]["low"] == 100.0 - 2 * expected_move
    assert result["two_sd"]["high"] == 100.0 + 2 * expected_move


def test_compute_implied_range_wider_with_more_dte():
    short = compute_implied_range(spot=100.0, atm_iv=0.20, dte=1.0)
    longer = compute_implied_range(spot=100.0, atm_iv=0.20, dte=10.0)
    assert longer["expected_move"] > short["expected_move"]


def test_compute_implied_range_zero_dte_uses_floor_not_zero():
    result = compute_implied_range(spot=100.0, atm_iv=0.20, dte=0.0)
    assert result["expected_move"] is not None
    assert result["expected_move"] > 0


def test_compute_implied_range_invalid_inputs():
    assert compute_implied_range(spot=0.0, atm_iv=0.20, dte=1.0)["expected_move"] is None
    assert compute_implied_range(spot=100.0, atm_iv=0.0, dte=1.0)["expected_move"] is None
