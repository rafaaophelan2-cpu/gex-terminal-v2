import hashlib

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import app.api.routes_auth as routes_auth
import app.api.routes_rest as routes_rest
import app.services.ai_context as ai_context
from app.main import app

FAKE_USER = {
    "username": "trader1",
    "name": "Trader Uno",
    "password_hash": hashlib.sha256(b"correcthorse").hexdigest(),
}

FAKE_SNAPSHOTS = [
    {"time": "09:30", "spot": 100.0, "net_gex": -2.0, "strikes": [{"call_gex": 3.0, "put_gex": -5.0}]},
]


@pytest.fixture
def authed_client(monkeypatch):
    routes_auth.login_rate_limiter._failures.clear()
    routes_auth.login_rate_limiter._locked_until.clear()

    async def _fake_fetch_user(username):
        return FAKE_USER if username == "trader1" else None

    async def _fake_update_password_hash(username, new_hash):
        pass

    monkeypatch.setattr(routes_auth, "fetch_user_by_username", _fake_fetch_user)
    monkeypatch.setattr(routes_auth, "update_user_password_hash", _fake_update_password_hash)

    client = TestClient(app, base_url="https://testserver")
    client.post("/auth/login", json={"username": "trader1", "password": "correcthorse"})
    return client


def test_drift_requires_auth():
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/market/drift?symbol=QQQ")
    assert resp.status_code == 401


def test_drift_returns_series_for_authed_user(authed_client, monkeypatch):
    async def _fake_history(symbol, start_utc=None, end_utc=None, limit=1000):
        assert symbol == "QQQ"
        return FAKE_SNAPSHOTS

    monkeypatch.setattr(routes_rest, "fetch_gex_history", _fake_history)

    resp = authed_client.get("/market/drift?symbol=QQQ")
    assert resp.status_code == 200
    body = resp.json()
    assert body["time"] == ["09:30"]
    assert body["call_gex"] == [3.0]
    assert body["put_gex"] == [-5.0]


def test_drift_otm_only_query_param_reaches_compute_drift_series(authed_client, monkeypatch):
    # Confirma el wiring del endpoint, no la lógica de filtrado en sí
    # (ver tests/domain/test_drift.py para eso) -- que otm_only=true en la
    # URL de verdad llegue como otm_only=True a compute_drift_series.
    seen = {}

    async def _fake_history(symbol, start_utc=None, end_utc=None, limit=1000):
        return FAKE_SNAPSHOTS

    def _fake_compute_drift_series(snapshots, otm_only=False):
        seen["otm_only"] = otm_only
        return {"time": [], "spot": [], "call_gex": [], "put_gex": [], "net_gex": []}

    monkeypatch.setattr(routes_rest, "fetch_gex_history", _fake_history)
    monkeypatch.setattr(routes_rest, "compute_drift_series", _fake_compute_drift_series)

    resp = authed_client.get("/market/drift?symbol=QQQ&otm_only=true")
    assert resp.status_code == 200
    assert seen["otm_only"] is True


def test_heatmap_includes_gamma_trend_lines(authed_client, monkeypatch):
    snapshots = [
        {
            "time": "09:30", "spot": 100.0,
            "strikes": [
                {"strike": 95.0, "net_gex": -8.0}, {"strike": 105.0, "net_gex": 6.0},
            ],
        },
    ]

    async def _fake_history(symbol, start_utc=None, end_utc=None, limit=1000):
        return snapshots

    monkeypatch.setattr(routes_rest, "fetch_gex_history", _fake_history)

    resp = authed_client.get("/market/heatmap?symbol=QQQ")
    assert resp.status_code == 200
    body = resp.json()
    assert body["gamma_peak"] == [105.0]
    assert body["gamma_trough"] == [95.0]
    assert "gamma_zero" in body
    assert "z" in body  # sigue trayendo la matriz de siempre, no la reemplaza


def test_heatmap_charm_includes_charm_zero_line(authed_client, monkeypatch):
    snapshots = [
        {
            "time": "09:30", "spot": 100.0,
            "strikes": [{"strike": 100.0, "net_gex": 0.0, "net_chex": 5.0}],
        },
    ]

    async def _fake_history(symbol, start_utc=None, end_utc=None, limit=1000):
        return snapshots

    monkeypatch.setattr(routes_rest, "fetch_gex_history", _fake_history)

    resp = authed_client.get("/market/heatmap-charm?symbol=QQQ")
    assert resp.status_code == 200
    body = resp.json()
    assert body["charm_zero"] == [100.0]


def test_vix_requires_auth():
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/market/vix")
    assert resp.status_code == 401


def test_vix_returns_value_and_classification(authed_client, monkeypatch):
    async def _fake_fetch_vix():
        return 27.5

    monkeypatch.setattr(routes_rest, "fetch_vix", _fake_fetch_vix)

    resp = authed_client.get("/market/vix")
    assert resp.status_code == 200
    body = resp.json()
    assert body["value"] == 27.5
    assert body["status"] == "Volatilidad Alta"
    assert body["color"] == "#F59E0B"


def test_available_dates_requires_auth():
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/market/available-dates?symbol=QQQ")
    assert resp.status_code == 401


def test_available_dates_returns_list(authed_client, monkeypatch):
    async def _fake_available_dates(symbol, tz):
        assert symbol == "QQQ"
        return ["2026-09-11", "2026-09-10"]

    monkeypatch.setattr(routes_rest, "fetch_available_dates", _fake_available_dates)

    resp = authed_client.get("/market/available-dates?symbol=QQQ")
    assert resp.status_code == 200
    assert resp.json() == {"dates": ["2026-09-11", "2026-09-10"]}


def test_vix_term_structure_requires_auth():
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/market/vix-term-structure")
    assert resp.status_code == 401


def test_vix_term_structure_returns_state(authed_client, monkeypatch):
    async def _fake_term_structure():
        return {"vix": 15.0, "vix3m": 18.0, "state": "contango"}

    monkeypatch.setattr(routes_rest, "fetch_vix_term_structure", _fake_term_structure)

    resp = authed_client.get("/market/vix-term-structure")
    assert resp.status_code == 200
    assert resp.json() == {"vix": 15.0, "vix3m": 18.0, "state": "contango"}


def test_vix_term_structure_no_data_returns_na(authed_client, monkeypatch):
    async def _fake_term_structure_empty():
        return {}

    monkeypatch.setattr(routes_rest, "fetch_vix_term_structure", _fake_term_structure_empty)

    resp = authed_client.get("/market/vix-term-structure")
    assert resp.status_code == 200
    assert resp.json()["state"] == "n/a"


class _FakeFeed:
    def __init__(self):
        self.spot_price = 481.23
        self.nearest_exp_key = "2026-09-11:0"
        self.oi_is_volume_proxy = False
        self.macro_levels = {}
        self.df = pd.DataFrame([
            {"strike": 475.0, "exp_key": "2026-09-11:0", "dte": 0, "net_gex": -5.0, "call_gex": 1.0, "put_gex": -6.0,
             "net_dex": 1.0, "net_tex": -1.0, "net_vex": 1.0, "net_chex": -1.0, "net_vanna": 1.0},
            {"strike": 485.0, "exp_key": "2026-09-11:0", "dte": 0, "net_gex": 3.0, "call_gex": 4.0, "put_gex": -1.0,
             "net_dex": 1.0, "net_tex": -1.0, "net_vex": 1.0, "net_chex": -1.0, "net_vanna": 1.0},
        ])


def test_implied_range_requires_auth():
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/market/implied-range?symbol=QQQ")
    assert resp.status_code == 401


def test_implied_range_no_active_feed_returns_nulls(authed_client, monkeypatch):
    monkeypatch.setattr(routes_rest.feed_registry, "get", lambda symbol: None)
    resp = authed_client.get("/market/implied-range?symbol=QQQ")
    assert resp.status_code == 200
    assert resp.json() == {"expected_move": None, "one_sd": None, "two_sd": None}


def test_implied_range_with_active_feed_returns_band(authed_client, monkeypatch):
    monkeypatch.setattr(routes_rest.feed_registry, "get", lambda symbol: _FakeFeed())
    resp = authed_client.get("/market/implied-range?symbol=QQQ")
    assert resp.status_code == 200
    body = resp.json()
    assert body["expected_move"] is not None
    assert body["one_sd"]["low"] < 481.23 < body["one_sd"]["high"]


def test_compounded_levels_requires_auth():
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/market/compounded-levels?symbol=QQQ")
    assert resp.status_code == 401


def test_compounded_levels_no_active_feed_returns_empty(authed_client, monkeypatch):
    monkeypatch.setattr(routes_rest.feed_registry, "get", lambda symbol: None)
    resp = authed_client.get("/market/compounded-levels?symbol=QQQ")
    assert resp.status_code == 200
    assert resp.json() == {"ratio": None, "ndx_spot": None, "matches": []}


def test_compounded_levels_formats_matches_as_dicts(authed_client, monkeypatch):
    from app.domain.compounded_levels import CompoundedLevel

    monkeypatch.setattr(routes_rest.feed_registry, "get", lambda symbol: _FakeFeed())

    async def _fake_ndx_compounded(symbol, spot, metrics):
        return {
            "ratio": 41.0,
            "ndx_spot": 19730.4,
            "matches": [CompoundedLevel("Call Wall 1", 485.0, "Call Wall 1 NDX", 485.1)],
        }

    monkeypatch.setattr(routes_rest, "fetch_ndx_compounded_levels", _fake_ndx_compounded)

    resp = authed_client.get("/market/compounded-levels?symbol=QQQ")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ratio"] == 41.0
    assert body["matches"] == [{
        "primary_name": "Call Wall 1", "primary_value": 485.0,
        "secondary_name": "Call Wall 1 NDX", "secondary_value_translated": 485.1,
    }]


def test_refresh_oi_requires_auth():
    client = TestClient(app, base_url="https://testserver")
    resp = client.post("/market/refresh-oi?symbol=VIX")
    assert resp.status_code == 401


def test_refresh_oi_rejects_symbol_not_using_marketdata(authed_client):
    resp = authed_client.post("/market/refresh-oi?symbol=QQQ")
    assert resp.status_code == 400


def test_refresh_oi_forces_fetch_and_reports_strike_count(authed_client, monkeypatch):
    async def _fake_fetch(symbol, force=False):
        assert symbol == "VIX"
        assert force is True
        return {(15.0, "call"): 100, (15.0, "put"): 50}

    monkeypatch.setattr(routes_rest, "fetch_oi_map", _fake_fetch)

    resp = authed_client.post("/market/refresh-oi?symbol=VIX")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "strikes": 2}


def test_refresh_oi_reports_failure(authed_client, monkeypatch):
    async def _fake_fetch(symbol, force=False):
        return None

    monkeypatch.setattr(routes_rest, "fetch_oi_map", _fake_fetch)

    resp = authed_client.post("/market/refresh-oi?symbol=NDX")
    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "strikes": 0}


def test_ai_diagnosis_requires_auth():
    client = TestClient(app, base_url="https://testserver")
    resp = client.post("/market/ai-diagnosis", json={"symbol": "QQQ"})
    assert resp.status_code == 401


def test_ai_diagnosis_without_active_feed_returns_409(authed_client, monkeypatch):
    monkeypatch.setattr(ai_context.feed_registry, "get", lambda symbol: None)
    resp = authed_client.post("/market/ai-diagnosis", json={"symbol": "QQQ"})
    assert resp.status_code == 409


async def _fake_candles(symbol, day):
    return [{"time": "09:30", "open": 478.0, "high": 481.0, "low": 477.0, "close": 480.5}]


async def _fake_vix():
    return 18.5


async def _fake_session_profile(session_key):
    return None


def test_ai_diagnosis_uses_groq_when_available(authed_client, monkeypatch):
    monkeypatch.setattr(ai_context.feed_registry, "get", lambda symbol: _FakeFeed())
    monkeypatch.setattr(ai_context, "fetch_price_history", _fake_candles)
    monkeypatch.setattr(ai_context, "fetch_vix", _fake_vix)
    monkeypatch.setattr(ai_context, "fetch_session_profile", _fake_session_profile)

    async def _fake_query_groq(system_prompt, user_prompt):
        assert "481.23" in system_prompt
        return "diagnóstico narrativo de groq"

    monkeypatch.setattr(routes_rest, "query_groq", _fake_query_groq)

    resp = authed_client.post("/market/ai-diagnosis", json={"symbol": "QQQ", "tipo_analisis": "Posibles Escenarios"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "groq"
    assert body["text"] == "diagnóstico narrativo de groq"


def test_ai_diagnosis_daily_briefing_uses_short_user_prompt(authed_client, monkeypatch):
    # Botón "Análisis para el día" de Briefings -- debe armar el user_prompt
    # corto (build_daily_briefing_user_prompt), no el informe completo de
    # siempre (build_default_user_prompt).
    monkeypatch.setattr(ai_context.feed_registry, "get", lambda symbol: _FakeFeed())
    monkeypatch.setattr(ai_context, "fetch_price_history", _fake_candles)
    monkeypatch.setattr(ai_context, "fetch_vix", _fake_vix)
    monkeypatch.setattr(ai_context, "fetch_session_profile", _fake_session_profile)

    async def _fake_query_groq(system_prompt, user_prompt):
        assert "briefing corto" in user_prompt
        assert "informe cuantitativo completo" not in user_prompt
        return "briefing corto de groq"

    monkeypatch.setattr(routes_rest, "query_groq", _fake_query_groq)

    resp = authed_client.post("/market/ai-diagnosis", json={"symbol": "QQQ", "tipo_analisis": "Análisis para el día"})
    assert resp.status_code == 200
    assert resp.json()["text"] == "briefing corto de groq"


def test_ai_diagnosis_manual_conversion_ratio_overrides_default(authed_client, monkeypatch):
    # El ratio NQ_QQQ_RATIO fijo puede quedar desactualizado -- un ratio
    # manual mandado desde la web (ver InputParameter ManualRatio del
    # indicador de Quantower, mismo concepto) debe tener prioridad total
    # y llegar tal cual al prompt.
    monkeypatch.setattr(ai_context.feed_registry, "get", lambda symbol: _FakeFeed())
    monkeypatch.setattr(ai_context, "fetch_price_history", _fake_candles)
    monkeypatch.setattr(ai_context, "fetch_vix", _fake_vix)
    monkeypatch.setattr(ai_context, "fetch_session_profile", _fake_session_profile)

    async def _fake_query_groq(system_prompt, user_prompt):
        assert "39.5000" in system_prompt  # el ratio manual, no 41.1250
        return "ok"

    monkeypatch.setattr(routes_rest, "query_groq", _fake_query_groq)

    resp = authed_client.post(
        "/market/ai-diagnosis",
        json={"symbol": "QQQ", "tipo_analisis": "Intradía", "conversion_ratio": 39.5},
    )
    assert resp.status_code == 200
    assert resp.json()["text"] == "ok"


def test_ai_diagnosis_falls_back_to_local_when_groq_unavailable(authed_client, monkeypatch):
    monkeypatch.setattr(ai_context.feed_registry, "get", lambda symbol: _FakeFeed())
    monkeypatch.setattr(ai_context, "fetch_price_history", _fake_candles)
    monkeypatch.setattr(ai_context, "fetch_vix", _fake_vix)
    monkeypatch.setattr(ai_context, "fetch_session_profile", _fake_session_profile)

    async def _fake_query_groq_none(system_prompt, user_prompt):
        return None

    monkeypatch.setattr(routes_rest, "query_groq", _fake_query_groq_none)

    resp = authed_client.post("/market/ai-diagnosis", json={"symbol": "QQQ"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "local"
    assert "Resumen Rápido" in body["text"]


class _FakeMultiExpFeed:
    def __init__(self):
        self.spot_price = 480.0
        self.df = pd.DataFrame([
            {"strike": 480.0, "exp_key": "2026-09-11:0", "exp_date": "2026-09-11", "dte": 0, "net_gex": 10_000_000.0},
            {"strike": 480.0, "exp_key": "2026-09-21:10", "exp_date": "2026-09-21", "dte": 10, "net_gex": 3_000_000.0},
            {"strike": 480.0, "exp_key": "2026-10-01:20", "exp_date": "2026-10-01", "dte": 20, "net_gex": 1_000_000.0},
        ])
        # GRID/3D SURFACE/3D VOL SURFACE ahora leen deep_df (cadena ancha),
        # no df (la angosta del tick en vivo) -- ver market_feed.py.
        self.deep_df = self.df


def test_expirations_requires_auth():
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/market/expirations?symbol=QQQ")
    assert resp.status_code == 401


def test_expirations_returns_empty_without_active_feed(authed_client, monkeypatch):
    monkeypatch.setattr(routes_rest.feed_registry, "get", lambda symbol: None)
    resp = authed_client.get("/market/expirations?symbol=QQQ")
    assert resp.status_code == 200
    assert resp.json() == {"expirations": []}


def test_expirations_lists_all_dtes_sorted(authed_client, monkeypatch):
    monkeypatch.setattr(routes_rest.feed_registry, "get", lambda symbol: _FakeMultiExpFeed())
    resp = authed_client.get("/market/expirations?symbol=QQQ")
    assert resp.status_code == 200
    dtes = [e["dte"] for e in resp.json()["expirations"]]
    assert dtes == [0, 10, 20]


def test_gamma_grid_requires_auth():
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/market/gamma-grid?symbol=QQQ")
    assert resp.status_code == 401


def test_gamma_grid_without_active_feed_returns_409(authed_client, monkeypatch):
    monkeypatch.setattr(routes_rest.feed_registry, "get", lambda symbol: None)
    resp = authed_client.get("/market/gamma-grid?symbol=QQQ")
    assert resp.status_code == 409


def test_gamma_grid_defaults_to_nearest_expirations_when_none_selected(authed_client, monkeypatch):
    monkeypatch.setattr(routes_rest.feed_registry, "get", lambda symbol: _FakeMultiExpFeed())
    resp = authed_client.get("/market/gamma-grid?symbol=QQQ")
    assert resp.status_code == 200
    body = resp.json()
    assert [c["exp_key"] for c in body["columns"]] == ["2026-09-11:0", "2026-09-21:10", "2026-10-01:20"]


def test_gamma_grid_respects_explicit_exp_keys(authed_client, monkeypatch):
    monkeypatch.setattr(routes_rest.feed_registry, "get", lambda symbol: _FakeMultiExpFeed())
    resp = authed_client.get("/market/gamma-grid?symbol=QQQ&exp_keys=2026-09-11:0,2026-10-01:20")
    assert resp.status_code == 200
    body = resp.json()
    assert [c["exp_key"] for c in body["columns"]] == ["2026-09-11:0", "2026-10-01:20"]
    assert body["values"][0] == [10_000_000.0, 1_000_000.0]


def test_gamma_surface_requires_auth():
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/market/gamma-surface?symbol=QQQ")
    assert resp.status_code == 401


def test_gamma_surface_without_active_feed_returns_409(authed_client, monkeypatch):
    monkeypatch.setattr(routes_rest.feed_registry, "get", lambda symbol: None)
    resp = authed_client.get("/market/gamma-surface?symbol=QQQ")
    assert resp.status_code == 409


def test_gamma_surface_defaults_to_nearest_expirations_when_none_selected(authed_client, monkeypatch):
    monkeypatch.setattr(routes_rest.feed_registry, "get", lambda symbol: _FakeMultiExpFeed())
    resp = authed_client.get("/market/gamma-surface?symbol=QQQ")
    assert resp.status_code == 200
    body = resp.json()
    # Mismo fixture que GRID: solo 3 expiraciones disponibles, todas caen
    # dentro de DEFAULT_SURFACE_EXPIRATION_COUNT (10) igual que del GRID (6).
    assert [c["exp_key"] for c in body["columns"]] == ["2026-09-11:0", "2026-09-21:10", "2026-10-01:20"]


class _FakeManyExpFeed:
    """>6 expiraciones -- para distinguir el default de SURFACE (10) del
    default de GRID (6) sin ambigüedad."""

    def __init__(self):
        self.spot_price = 480.0
        rows = [
            {"strike": 480.0, "exp_key": f"exp{i}", "exp_date": f"2026-09-{11 + i:02d}", "dte": i, "net_gex": float(i)}
            for i in range(8)
        ]
        self.df = pd.DataFrame(rows)
        self.deep_df = self.df


def test_gamma_surface_default_count_differs_from_grid_default(authed_client, monkeypatch):
    monkeypatch.setattr(routes_rest.feed_registry, "get", lambda symbol: _FakeManyExpFeed())

    grid_resp = authed_client.get("/market/gamma-grid?symbol=QQQ")
    surface_resp = authed_client.get("/market/gamma-surface?symbol=QQQ")

    assert len(grid_resp.json()["columns"]) == 6
    assert len(surface_resp.json()["columns"]) == 8  # las 8 disponibles, tope real es 10


def test_gamma_surface_respects_explicit_exp_keys(authed_client, monkeypatch):
    monkeypatch.setattr(routes_rest.feed_registry, "get", lambda symbol: _FakeMultiExpFeed())
    resp = authed_client.get("/market/gamma-surface?symbol=QQQ&exp_keys=2026-09-11:0,2026-10-01:20")
    assert resp.status_code == 200
    body = resp.json()
    assert [c["exp_key"] for c in body["columns"]] == ["2026-09-11:0", "2026-10-01:20"]


class _FakeVolSurfaceFeed:
    def __init__(self):
        self.spot_price = 100.0
        self.df = pd.DataFrame([
            {"strike": 95.0, "exp_key": "2026-09-11:0", "exp_date": "2026-09-11", "dte": 0, "iv_c": 0.30, "iv_p": 0.35},
            {"strike": 105.0, "exp_key": "2026-09-11:0", "exp_date": "2026-09-11", "dte": 0, "iv_c": 0.28, "iv_p": 0.40},
        ])
        self.deep_df = self.df


def test_vol_surface_requires_auth():
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/market/vol-surface?symbol=QQQ")
    assert resp.status_code == 401


def test_vol_surface_without_active_feed_returns_409(authed_client, monkeypatch):
    monkeypatch.setattr(routes_rest.feed_registry, "get", lambda symbol: None)
    resp = authed_client.get("/market/vol-surface?symbol=QQQ")
    assert resp.status_code == 409


def test_vol_surface_returns_iv_grid_with_otm_convention(authed_client, monkeypatch):
    monkeypatch.setattr(routes_rest.feed_registry, "get", lambda symbol: _FakeVolSurfaceFeed())
    resp = authed_client.get("/market/vol-surface?symbol=QQQ&exp_keys=2026-09-11:0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["strikes"] == [95.0, 105.0]
    assert body["values"][body["strikes"].index(95.0)] == pytest.approx([35.0])
    assert body["values"][body["strikes"].index(105.0)] == pytest.approx([28.0])
