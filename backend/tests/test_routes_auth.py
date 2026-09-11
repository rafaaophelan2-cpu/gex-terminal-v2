import hashlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
import app.api.routes_auth as routes_auth


FAKE_USER = {
    "username": "trader1",
    "name": "Trader Uno",
    "password_hash": hashlib.sha256(b"correcthorse").hexdigest(),
}


@pytest.fixture
def client():
    # Cada test arranca con el rate limiter limpio, para que un fallo
    # forzado en un test no bloquee al siguiente.
    routes_auth.login_rate_limiter._failures.clear()
    routes_auth.login_rate_limiter._locked_until.clear()
    # base_url https: la cookie de sesión se marca Secure, y el cliente de
    # test solo la persiste/reenvía si el transporte es https.
    return TestClient(app, base_url="https://testserver")


async def _fake_fetch_user_found(username: str):
    return FAKE_USER if username == "trader1" else None


async def _fake_fetch_user_not_found(username: str):
    return None


async def _fake_update_password_hash(username: str, new_hash: str):
    pass


def test_login_success_sets_cookie(client, monkeypatch):
    monkeypatch.setattr(routes_auth, "fetch_user_by_username", _fake_fetch_user_found)
    monkeypatch.setattr(routes_auth, "update_user_password_hash", _fake_update_password_hash)

    resp = client.post("/auth/login", json={"username": "trader1", "password": "correcthorse"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "gex_session" in resp.cookies


def test_login_wrong_password(client, monkeypatch):
    monkeypatch.setattr(routes_auth, "fetch_user_by_username", _fake_fetch_user_found)

    resp = client.post("/auth/login", json={"username": "trader1", "password": "wrongpass"})
    assert resp.status_code == 401


def test_login_unknown_user(client, monkeypatch):
    monkeypatch.setattr(routes_auth, "fetch_user_by_username", _fake_fetch_user_not_found)

    resp = client.post("/auth/login", json={"username": "ghost", "password": "whatever"})
    assert resp.status_code == 401


def test_login_rate_limit_after_5_failures(client, monkeypatch):
    monkeypatch.setattr(routes_auth, "fetch_user_by_username", _fake_fetch_user_found)

    for _ in range(5):
        client.post("/auth/login", json={"username": "trader1", "password": "wrongpass"})

    resp = client.post("/auth/login", json={"username": "trader1", "password": "correcthorse"})
    assert resp.status_code == 429


def test_me_requires_valid_cookie(client, monkeypatch):
    monkeypatch.setattr(routes_auth, "fetch_user_by_username", _fake_fetch_user_found)
    monkeypatch.setattr(routes_auth, "update_user_password_hash", _fake_update_password_hash)

    resp_no_cookie = client.get("/auth/me")
    assert resp_no_cookie.status_code == 401

    client.post("/auth/login", json={"username": "trader1", "password": "correcthorse"})
    resp_me = client.get("/auth/me")
    assert resp_me.status_code == 200
    assert resp_me.json()["username"] == "trader1"
