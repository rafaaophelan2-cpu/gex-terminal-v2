import hashlib

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
