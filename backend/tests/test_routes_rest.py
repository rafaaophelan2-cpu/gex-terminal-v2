import hashlib

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import app.api.routes_auth as routes_auth
import app.api.routes_rest as routes_rest
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
    monkeypatch.setattr(routes_rest.feed_registry, "get", lambda symbol: None)
    resp = authed_client.post("/market/ai-diagnosis", json={"symbol": "QQQ"})
    assert resp.status_code == 409


async def _fake_candles(symbol, day):
    return [{"time": "09:30", "open": 478.0, "high": 481.0, "low": 477.0, "close": 480.5}]


async def _fake_vix():
    return 18.5


def test_ai_diagnosis_uses_groq_when_available(authed_client, monkeypatch):
    monkeypatch.setattr(routes_rest.feed_registry, "get", lambda symbol: _FakeFeed())
    monkeypatch.setattr(routes_rest, "fetch_price_history", _fake_candles)
    monkeypatch.setattr(routes_rest, "fetch_vix", _fake_vix)

    async def _fake_query_groq(system_prompt, user_prompt):
        assert "481.23" in system_prompt
        return "diagnóstico narrativo de groq"

    monkeypatch.setattr(routes_rest, "query_groq", _fake_query_groq)

    resp = authed_client.post("/market/ai-diagnosis", json={"symbol": "QQQ", "tipo_analisis": "Intradía"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "groq"
    assert body["text"] == "diagnóstico narrativo de groq"


def test_ai_diagnosis_falls_back_to_local_when_groq_unavailable(authed_client, monkeypatch):
    monkeypatch.setattr(routes_rest.feed_registry, "get", lambda symbol: _FakeFeed())
    monkeypatch.setattr(routes_rest, "fetch_price_history", _fake_candles)
    monkeypatch.setattr(routes_rest, "fetch_vix", _fake_vix)

    async def _fake_query_groq_none(system_prompt, user_prompt):
        return None

    monkeypatch.setattr(routes_rest, "query_groq", _fake_query_groq_none)

    resp = authed_client.post("/market/ai-diagnosis", json={"symbol": "QQQ"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "local"
    assert "Resumen Rápido" in body["text"]
