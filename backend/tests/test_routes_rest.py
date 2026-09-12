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


class _FakeFeed:
    def __init__(self):
        self.spot_price = 481.23
        self.nearest_exp_key = "2026-09-11:0"
        self.df = pd.DataFrame([
            {"strike": 475.0, "exp_key": "2026-09-11:0", "dte": 0, "net_gex": -5.0, "call_gex": 1.0, "put_gex": -6.0,
             "net_dex": 1.0, "net_tex": -1.0, "net_vex": 1.0, "net_chex": -1.0, "net_vanna": 1.0},
            {"strike": 485.0, "exp_key": "2026-09-11:0", "dte": 0, "net_gex": 3.0, "call_gex": 4.0, "put_gex": -1.0,
             "net_dex": 1.0, "net_tex": -1.0, "net_vex": 1.0, "net_chex": -1.0, "net_vanna": 1.0},
        ])


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

    resp = authed_client.post("/market/ai-diagnosis", json={"symbol": "QQQ", "tipo_analisis": "Intradía"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "groq"
    assert body["text"] == "diagnóstico narrativo de groq"


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
