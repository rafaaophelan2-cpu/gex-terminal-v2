from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from app.domain.briefing_data import (
    build_briefing_payload_from_snapshot,
    build_briefing_payload_live,
    compute_market_status,
    filter_calendar_today,
)

NY_TZ = ZoneInfo("America/New_York")


def _ny(y, m, d, h, mi):
    return datetime(y, m, d, h, mi, tzinfo=NY_TZ)


def test_compute_market_status_premarket_before_open():
    assert compute_market_status(_ny(2026, 9, 17, 8, 0)) == "premarket"  # jueves


def test_compute_market_status_open_during_session():
    assert compute_market_status(_ny(2026, 9, 17, 12, 0)) == "open"
    assert compute_market_status(_ny(2026, 9, 17, 9, 30)) == "open"  # borde de apertura
    assert compute_market_status(_ny(2026, 9, 17, 16, 0)) == "open"  # borde de cierre


def test_compute_market_status_closed_after_hours_and_weekend():
    assert compute_market_status(_ny(2026, 9, 17, 16, 1)) == "closed"
    assert compute_market_status(_ny(2026, 9, 19, 12, 0)) == "closed"  # sábado


def test_filter_calendar_today_keeps_only_today_medium_high():
    calendar = [
        {"date": "2026-09-17", "time": "08:30", "event": "CPI", "impact": "high", "actual": None},
        {"date": "2026-09-17", "time": "10:00", "event": "ruido menor", "impact": "low", "actual": None},
        {"date": "2026-09-18", "time": "08:30", "event": "FOMC", "impact": "high", "actual": None},
        {"date": "2026-09-17", "time": "09:00", "event": "ya salió", "impact": "medium", "actual": "3.1%"},
    ]
    out = filter_calendar_today(calendar, "2026-09-17")
    assert {ev["event"] for ev in out} == {"CPI", "ya salió"}
    released = {ev["event"]: ev["released"] for ev in out}
    assert released["CPI"] is False
    assert released["ya salió"] is True


def test_filter_calendar_today_empty_for_no_calendar():
    assert filter_calendar_today(None, "2026-09-17") == []
    assert filter_calendar_today([], "2026-09-17") == []


def _live_df() -> pd.DataFrame:
    common = {"openInterest_c": 100, "openInterest_p": 80, "volume_c": 10, "volume_p": 8,
              "net_dex": 1.0, "call_dex": 0.6, "put_dex": 0.4, "net_tex": -2.0, "net_vex": 3.0,
              "net_chex": 0.5, "net_vanna": 0.2, "iv_c": 0.20, "iv_p": 0.22,
              "mark_c": 1.1, "mark_p": 0.9}
    # El flip sale del open interest (perfil de precio): en 495 dominan
    # las calls y en 505 las puts, con el mismo neto (20) a cada lado, así
    # que el gamma total cruza cero justo en el medio, en 500.
    rows = [
        {"strike": 495.0, "exp_key": "e0", "exp_date": "2026-09-17", "dte": 0,
         "net_gex": 50.0, "call_gex": 50.0, "put_gex": 0.0, **common},
        {"strike": 505.0, "exp_key": "e0", "exp_date": "2026-09-17", "dte": 0,
         "net_gex": -30.0, "call_gex": 0.0, "put_gex": -30.0, **common,
         "openInterest_c": 80, "openInterest_p": 100},
        {"strike": 500.0, "exp_key": "e7", "exp_date": "2026-09-24", "dte": 7,
         "net_gex": 999.0, "call_gex": 999.0, "put_gex": 0.0, **common},
    ]
    return pd.DataFrame(rows)


def test_build_briefing_payload_live_matches_shape_and_reuses_metrics():
    df = _live_df()
    payload = build_briefing_payload_live(
        symbol="QQQ", df=df, spot_price=500.0, atm_iv=0.21, dte_0dte=0.0,
        market_status="open", timestamp_utc="2026-09-17T14:00:00+00:00",
        data_as_of="2026-09-17T13:59:58+00:00",
        vix_term_structure={"vix": 17.1, "vix3m": 19.0, "state": "contango"},
        calendar_today=[{"date": "2026-09-17", "event": "CPI", "impact": "high", "released": False}],
        opening_net_gex=10.0,
    )

    assert set(payload.keys()) == {
        "meta", "totals_0dte", "totals_next", "ladder_0dte", "ladder_next",
        "flip_0dte", "flip_next", "straddle_atm_0dte", "expected_move",
        "implied_range", "net_gex_change_since_open", "vix", "calendar_today",
    }
    assert payload["meta"]["symbol"] == "QQQ"
    assert payload["meta"]["expiration_0dte"] == "e0"
    assert payload["meta"]["expiration_next"] == "e7"
    assert payload["meta"]["market_status"] == "open"
    assert payload["meta"]["data_as_of"] == "2026-09-17T13:59:58+00:00"
    assert "net_gex" in payload["meta"]["units"]

    # totals_0dte viene de compute_metrics_for_dte -- 50 - 30 = 20 de net_gex.
    assert payload["totals_0dte"]["net_gex"] == 20.0
    assert payload["totals_0dte"]["dex"] == 2.0  # 1.0 + 1.0 (dos strikes de e0)
    assert payload["totals_next"]["net_gex"] == 999.0

    ladder_strikes = {row["strike"] for row in payload["ladder_0dte"]}
    assert ladder_strikes == {495.0, 505.0}
    row_495 = next(r for r in payload["ladder_0dte"] if r["strike"] == 495.0)
    assert row_495["call_oi"] == 100
    assert row_495["gex"] == 50.0
    assert row_495["vanna"] == 0.2
    assert row_495["charm"] == 0.5

    # Cruce del perfil de precio: casi en el medio de 495 y 505 (no exacto,
    # la gamma de Black-Scholes no es simétrica en precio).
    assert abs(payload["flip_0dte"] - 500.0) < 0.25
    # Un solo strike con más calls que puts: el gamma total nunca cambia de
    # signo. Antes caía al spot (500) y se mostraba como si fuera un flip.
    assert payload["flip_next"] is None

    assert payload["straddle_atm_0dte"]["straddle_price"] == 2.0  # 1.1 + 0.9
    assert payload["net_gex_change_since_open"] == 10.0  # 20 - 10

    assert payload["vix"] == {"vix": 17.1, "vix3m": 19.0, "term_structure": "contango"}
    assert payload["calendar_today"][0]["event"] == "CPI"


def test_build_briefing_payload_live_no_real_next_expiration_nulls_it_out():
    # Solo 0DTE cargado en el df -- ni ladder_next ni totals_next deben
    # aparentar ser una segunda expiración real (ver oi_ladder.py:
    # resolve_expiration_key cae a 0dte cuando no hay una segunda).
    common = {"openInterest_c": 10, "openInterest_p": 10}
    df = pd.DataFrame([
        {"strike": 500.0, "exp_key": "e0", "exp_date": "2026-09-17", "dte": 0, "net_gex": 1.0, **common},
    ])
    payload = build_briefing_payload_live(
        symbol="QQQ", df=df, spot_price=500.0, atm_iv=0.20, dte_0dte=0.0,
        market_status="open", timestamp_utc="t", data_as_of="t",
        vix_term_structure=None, calendar_today=[], opening_net_gex=None,
    )
    assert payload["meta"]["expiration_next"] is None
    assert payload["ladder_next"] == []
    assert payload["flip_next"] is None
    assert payload["totals_next"]["net_gex"] is None
    assert payload["net_gex_change_since_open"] is None  # sin opening_net_gex


def test_build_briefing_payload_from_snapshot_reconstructs_partial_data():
    snapshot = {
        "created_at": "2026-09-16T20:00:05+00:00",
        "time": "15:59",
        "spot": 500.0,
        "atm_iv": 0.19,
        "net_gex": 25.0,
        "strikes": [
            {"strike": 495.0, "net_gex": -8.0, "call_gex": 1.0, "put_gex": -9.0, "net_chex": 2.0},
            {"strike": 505.0, "net_gex": 33.0, "call_gex": 33.0, "put_gex": 0.0, "net_chex": 1.0},
        ],
    }
    payload = build_briefing_payload_from_snapshot(
        symbol="QQQ", snapshot=snapshot, market_status="closed", timestamp_utc="2026-09-17T02:00:00+00:00",
        vix_term_structure={"vix": 15.0, "vix3m": 18.0, "state": "contango"},
        calendar_today=[], opening_net_gex=20.0,
    )

    assert payload["meta"]["market_status"] == "closed"
    assert payload["meta"]["data_as_of"] == "2026-09-16T20:00:05+00:00"  # created_at del snapshot, no 'ahora'
    assert payload["meta"]["expiration_0dte"] is None

    assert payload["totals_0dte"]["net_gex"] == 25.0
    assert payload["totals_0dte"]["chex"] == 3.0  # 2.0 + 1.0
    assert payload["totals_0dte"]["dex"] is None  # nunca se guardó en el snapshot

    assert payload["ladder_0dte"] == []  # sin OI/vanna reales guardados, mejor vacío que a medias
    assert payload["straddle_atm_0dte"] is None
    assert payload["implied_range"] is None

    # Snapshot sin open interest: flip por la suma acumulada, que pasa de -8
    # (495) a +25 (505); el cruce interpolado cae en 495 + 10 * 8/33.
    # Antes idxmin(|acumulada|) devolvía 495, que no es donde cruza.
    assert abs(payload["flip_0dte"] - (495.0 + 10.0 * 8.0 / 33.0)) < 1e-9
    assert payload["net_gex_change_since_open"] == 5.0  # 25 - 20


def test_build_briefing_payload_from_snapshot_none_for_invalid_snapshot():
    assert build_briefing_payload_from_snapshot(
        "QQQ", None, "closed", "t", None, [], None,
    ) is None
    assert build_briefing_payload_from_snapshot(
        "QQQ", {"spot": 0.0, "strikes": []}, "closed", "t", None, [], None,
    ) is None
