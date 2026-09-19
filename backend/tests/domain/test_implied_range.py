import math
from datetime import datetime
from zoneinfo import ZoneInfo

from app.domain.implied_range import compute_implied_range

NY_TZ = ZoneInfo("America/New_York")


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


def test_compute_implied_range_zero_dte_scales_with_time_to_close():
    # Bug real (ver gex_terminal_v2_lessons): el piso fijo de 0.1 dias para
    # 0DTE ignoraba cuanto faltaba de verdad para el cierre -- a las 10am
    # (6h para el cierre) y a las 3pm (1h para el cierre) daba EXACTAMENTE
    # el mismo expected_move, cuando deberian ser bien distintos.
    morning = datetime(2026, 9, 18, 10, 0, tzinfo=NY_TZ)   # 6h para el cierre (16:00 NY)
    afternoon = datetime(2026, 9, 18, 15, 0, tzinfo=NY_TZ)  # 1h para el cierre
    result_morning = compute_implied_range(spot=100.0, atm_iv=0.20, dte=0.0, now=morning)
    result_afternoon = compute_implied_range(spot=100.0, atm_iv=0.20, dte=0.0, now=afternoon)
    assert result_morning["expected_move"] > result_afternoon["expected_move"]


def test_compute_implied_range_zero_dte_matches_fraction_of_day_to_close():
    # Ancla el valor exacto a la fraccion REAL del dia calendario que falta
    # hasta el cierre de mercado (16:00 hora NY) -- no un piso arbitrario.
    now = datetime(2026, 9, 18, 10, 0, tzinfo=NY_TZ)  # 6h para el cierre
    result = compute_implied_range(spot=100.0, atm_iv=0.20, dte=0.0, now=now)
    fraction_of_day = 6.0 / 24.0
    expected_dte_years = fraction_of_day / 365.0
    expected_move = 100.0 * 0.20 * math.sqrt(expected_dte_years)
    assert abs(result["expected_move"] - expected_move) < 1e-9


def test_compute_implied_range_zero_dte_after_close_uses_small_floor_not_negative():
    # Si ya paso el cierre (edge case, no deberia pasar en produccion con un
    # feed activo, pero no debe crashear ni devolver un numero negativo/None).
    now = datetime(2026, 9, 18, 18, 0, tzinfo=NY_TZ)  # 2h DESPUES del cierre
    result = compute_implied_range(spot=100.0, atm_iv=0.20, dte=0.0, now=now)
    assert result["expected_move"] is not None
    assert result["expected_move"] > 0


def test_compute_implied_range_naive_now_treated_as_ny_wall_clock():
    # Bug real (code review 2026-09-18): un 'now' naive (sin tzinfo) se
    # interpretaba vía .astimezone(NY_TZ) como si estuviera en la timezone
    # LOCAL DEL SISTEMA (lo que sea que corra en el server, ej. UTC en
    # Render), no como hora de NY -- un caller que arma un 'now' naive
    # pensando "son las 10am en NY" se desalinearía en varias horas sin
    # ningún error visible. Un 'now' naive debe tratarse como si YA fuera
    # hora de pared de NY, no reinterpretarse contra otra zona.
    naive_now = datetime(2026, 9, 18, 10, 0)  # sin tzinfo
    aware_now = datetime(2026, 9, 18, 10, 0, tzinfo=NY_TZ)
    naive_result = compute_implied_range(spot=100.0, atm_iv=0.20, dte=0.0, now=naive_now)
    aware_result = compute_implied_range(spot=100.0, atm_iv=0.20, dte=0.0, now=aware_now)
    assert naive_result["expected_move"] == aware_result["expected_move"]


def test_compute_implied_range_positive_dte_ignores_now():
    # El branch dte>0 (multi-dia) no debe verse afectado por el fix de 0DTE
    # -- mismo resultado exista o no un 'now', y sin importar la hora.
    without_now = compute_implied_range(spot=100.0, atm_iv=0.20, dte=1.0)
    with_now = compute_implied_range(
        spot=100.0, atm_iv=0.20, dte=1.0, now=datetime(2026, 9, 18, 15, 59, tzinfo=NY_TZ)
    )
    assert without_now["expected_move"] == with_now["expected_move"]
