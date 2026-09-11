import math

import pandas as pd

from app.domain.gamma_grid import compute_gamma_grid, list_expirations

DF = pd.DataFrame([
    {"strike": 100.0, "exp_key": "2026-09-11:0", "exp_date": "2026-09-11", "dte": 0, "net_gex": 10_000_000.0},
    {"strike": 105.0, "exp_key": "2026-09-11:0", "exp_date": "2026-09-11", "dte": 0, "net_gex": -2_000_000.0},
    {"strike": 100.0, "exp_key": "2026-09-21:10", "exp_date": "2026-09-21", "dte": 10, "net_gex": 10_000_000.0},
    {"strike": 110.0, "exp_key": "2026-09-21:10", "exp_date": "2026-09-21", "dte": 10, "net_gex": 3_000_000.0},
])


def test_list_expirations_groups_and_sorts_by_dte():
    exps = list_expirations(DF)
    assert [e["exp_key"] for e in exps] == ["2026-09-11:0", "2026-09-21:10"]
    assert exps[0]["dte"] == 0
    assert exps[0]["net_gex"] == 8_000_000.0  # 10M - 2M
    assert exps[1]["dte"] == 10


def test_list_expirations_empty_input():
    assert list_expirations(pd.DataFrame()) == []


def test_compute_gamma_grid_empty_when_no_exp_keys_selected():
    grid = compute_gamma_grid(DF, [])
    assert grid == {"strikes": [], "columns": [], "values": [], "weights": [], "net_by_column": [], "max_abs_weight": 1.0}


def test_compute_gamma_grid_builds_strike_by_expiration_matrix():
    grid = compute_gamma_grid(DF, ["2026-09-11:0", "2026-09-21:10"])

    assert grid["strikes"] == [100.0, 105.0, 110.0]
    assert [c["exp_key"] for c in grid["columns"]] == ["2026-09-11:0", "2026-09-21:10"]
    assert [c["dte"] for c in grid["columns"]] == [0, 10]

    # strike 100 aparece en ambas expiraciones con el mismo net_gex real (10M).
    row_100 = grid["values"][grid["strikes"].index(100.0)]
    assert row_100 == [10_000_000.0, 10_000_000.0]

    # strike 105 solo existe en la expiración 0DTE; el resto queda en 0.
    row_105 = grid["values"][grid["strikes"].index(105.0)]
    assert row_105 == [-2_000_000.0, 0.0]

    assert grid["net_by_column"] == [8_000_000.0, 13_000_000.0]


def test_compute_gamma_grid_weights_decay_with_dte_for_same_dollar_amount():
    # El pedido explícito del usuario: 10M a 0DTE debe pesar (colorear)
    # más fuerte que 10M a 10DTE, aunque el monto real mostrado sea igual.
    grid = compute_gamma_grid(DF, ["2026-09-11:0", "2026-09-21:10"])
    row_100 = grid["strikes"].index(100.0)
    weight_0dte = grid["weights"][row_100][0]
    weight_10dte = grid["weights"][row_100][1]

    assert weight_0dte == 10_000_000.0  # dte=0 -> /sqrt(1) = sin descuento
    assert weight_10dte == 10_000_000.0 / math.sqrt(11)
    assert weight_10dte < weight_0dte
    assert abs(weight_10dte) < abs(weight_0dte) * 0.4  # decae bastante para 10DTE


def test_compute_gamma_grid_max_abs_weight_matches_strongest_cell():
    grid = compute_gamma_grid(DF, ["2026-09-11:0", "2026-09-21:10"])
    all_weights = [abs(w) for row in grid["weights"] for w in row]
    assert grid["max_abs_weight"] == max(all_weights)
