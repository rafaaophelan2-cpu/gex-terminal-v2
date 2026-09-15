import pandas as pd

from app.domain.quantower import build_eod_levels_from_snapshot, build_live_levels_payload, compute_conversion_ratio


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
        {"strike": 495.0, "net_gex": 50.0, "call_gex": 50.0, "put_gex": 0.0, "exp_key": "2026-09-11:0", "dte": 0},
        {"strike": 505.0, "net_gex": -30.0, "call_gex": 0.0, "put_gex": -30.0, "exp_key": "2026-09-11:0", "dte": 0},
        # Otra expiración: get_nearest_dte_subset debe excluirla del feed de Quantower.
        {"strike": 520.0, "net_gex": 999.0, "call_gex": 999.0, "put_gex": 0.0, "exp_key": "2026-09-18:7", "dte": 7},
    ])
    payload = build_live_levels_payload(df, spot_price=500.0, conversion_ratio=40.0)

    assert payload["qqq_spot"] == 500.0
    assert payload["conversion_ratio"] == 40.0
    assert set(payload.keys()) == {
        "qqq_spot", "conversion_ratio", "cw1", "cw2", "cw3", "pw1", "pw2", "pw3",
        "zero_gamma", "gamma_wall", "levels",
    }
    strikes_pushed = {lvl["strike"] for lvl in payload["levels"]}
    assert strikes_pushed == {495.0, 505.0}
    assert all(isinstance(lvl["net_gex"], float) for lvl in payload["levels"])
    assert isinstance(payload["zero_gamma"], float)
    assert isinstance(payload["gamma_wall"], float)


def test_build_live_levels_payload_gamma_wall_uses_absolute_exposure():
    # 495: 10 calls + 10 puts -> se cancela a 0 en net_gex pero es 20 en
    # gamma absoluto. 505: 15 calls netos -> domina el Call Wall (net_gex)
    # pero el Gamma Wall sigue siendo 495 porque ahi hay mas gamma en juego.
    df = pd.DataFrame([
        {"strike": 495.0, "net_gex": 0.0, "call_gex": 10.0, "put_gex": -10.0, "exp_key": "e0", "dte": 0},
        {"strike": 505.0, "net_gex": 15.0, "call_gex": 15.0, "put_gex": 0.0, "exp_key": "e0", "dte": 0},
    ])
    payload = build_live_levels_payload(df, spot_price=500.0, conversion_ratio=40.0)
    assert payload["gamma_wall"] == 495.0
    assert payload["cw1"] == 505.0


def test_build_eod_levels_from_snapshot_computes_walls():
    snapshot = {
        "spot": 500.0,
        "time": "15:59",
        "atm_iv": 0.18,
        "strikes": [
            {"strike": 495.0, "net_gex": -8.0, "call_gex": 1.0, "put_gex": -9.0},
            {"strike": 505.0, "net_gex": 12.0, "call_gex": 12.0, "put_gex": 0.0},
        ],
    }
    levels = build_eod_levels_from_snapshot(snapshot)
    assert levels["spot"] == 500.0
    assert levels["as_of_time"] == "15:59"
    assert levels["atm_iv"] == 0.18
    assert levels["cw1"] == 505.0
    assert levels["pw1"] == 495.0


def test_build_eod_levels_from_snapshot_none_when_missing():
    assert build_eod_levels_from_snapshot(None) is None
    assert build_eod_levels_from_snapshot({}) is None
    assert build_eod_levels_from_snapshot({"spot": 0.0, "strikes": [{"strike": 1.0}]}) is None
    assert build_eod_levels_from_snapshot({"spot": 500.0, "strikes": []}) is None


def test_build_eod_levels_from_snapshot_none_when_strikes_missing_gex_columns():
    # Snapshots guardados antes de que existieran call_gex/put_gex en el
    # payload (no debería pasar en la práctica, pero no debe romper).
    snapshot = {"spot": 500.0, "strikes": [{"strike": 495.0, "net_gex": -8.0}]}
    assert build_eod_levels_from_snapshot(snapshot) is None


def test_build_live_levels_payload_gamma_wall_falls_back_to_spot_without_call_put_columns():
    # DataFrames viejos (o de un feed sin call_gex/put_gex por alguna
    # razon) no deben romper el payload -- gamma_wall cae al spot, mismo
    # criterio de fallback que compute_call_put_walls/compute_zero_gamma.
    df = pd.DataFrame([
        {"strike": 495.0, "net_gex": 50.0, "exp_key": "e0", "dte": 0},
        {"strike": 505.0, "net_gex": -30.0, "exp_key": "e0", "dte": 0},
    ])
    payload = build_live_levels_payload(df, spot_price=500.0, conversion_ratio=40.0)
    assert payload["gamma_wall"] == 500.0


def test_build_live_levels_payload_zero_gamma_is_the_flip_strike():
    # net_gex acumulado (ordenado por strike) cruza cero entre 495 (+50) y
    # 505 (-30) -- compute_zero_gamma ya se prueba a fondo en
    # tests/domain/test_gex_math.py, acá solo se confirma que el valor
    # llega tal cual al payload de Quantower (no se recalcula distinto).
    df = pd.DataFrame([
        {"strike": 495.0, "net_gex": 50.0, "exp_key": "e0", "dte": 0},
        {"strike": 505.0, "net_gex": -30.0, "exp_key": "e0", "dte": 0},
    ])
    payload = build_live_levels_payload(df, spot_price=500.0, conversion_ratio=40.0)
    assert payload["zero_gamma"] in (495.0, 505.0)
