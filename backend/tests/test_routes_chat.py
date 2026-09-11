import hashlib

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import app.api.routes_auth as routes_auth
import app.api.routes_chat as routes_chat
import app.services.ai_context as ai_context
from app.main import app

FAKE_USER = {
    "username": "trader1",
    "name": "Trader Uno",
    "password_hash": hashlib.sha256(b"correcthorse").hexdigest(),
}


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


async def _fake_candles(symbol, day):
    return [{"time": "09:30", "open": 478.0, "high": 481.0, "low": 477.0, "close": 480.5}]


async def _fake_vix():
    return 18.5


def test_get_chat_history_requires_auth():
    client = TestClient(app, base_url="https://testserver")
    resp = client.get("/chat/history")
    assert resp.status_code == 401


def test_get_chat_history_returns_stored_messages(authed_client, monkeypatch):
    async def _fake_fetch_chat_history(username, limit=50):
        assert username == "trader1"
        return [{"role": "user", "content": "hola"}, {"role": "assistant", "content": "hola, en qué te ayudo?"}]

    monkeypatch.setattr(routes_chat, "fetch_chat_history", _fake_fetch_chat_history)

    resp = authed_client.get("/chat/history")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "user"


def test_delete_chat_history_clears_only_current_user(authed_client, monkeypatch):
    cleared_for = []

    async def _fake_clear(username):
        cleared_for.append(username)

    monkeypatch.setattr(routes_chat, "clear_chat_history", _fake_clear)

    resp = authed_client.delete("/chat/history")
    assert resp.status_code == 200
    assert cleared_for == ["trader1"]


def test_post_chat_message_requires_auth():
    client = TestClient(app, base_url="https://testserver")
    resp = client.post("/chat/message", json={"symbol": "QQQ", "message": "hola"})
    assert resp.status_code == 401


def test_post_chat_message_rejects_empty_message(authed_client):
    resp = authed_client.post("/chat/message", json={"symbol": "QQQ", "message": "   "})
    assert resp.status_code == 400


def test_post_chat_message_without_active_feed_returns_409(authed_client, monkeypatch):
    monkeypatch.setattr(ai_context.feed_registry, "get", lambda symbol: None)
    resp = authed_client.post("/chat/message", json={"symbol": "QQQ", "message": "cómo está el mercado?"})
    assert resp.status_code == 409


def test_post_chat_message_saves_both_messages_and_uses_groq(authed_client, monkeypatch):
    monkeypatch.setattr(ai_context.feed_registry, "get", lambda symbol: _FakeFeed())
    monkeypatch.setattr(ai_context, "fetch_price_history", _fake_candles)
    monkeypatch.setattr(ai_context, "fetch_vix", _fake_vix)

    async def _fake_fetch_chat_history(username, limit=50):
        return [{"role": "user", "content": "hola"}, {"role": "assistant", "content": "hola, en qué te ayudo?"}]

    monkeypatch.setattr(routes_chat, "fetch_chat_history", _fake_fetch_chat_history)

    saved = []

    async def _fake_insert(username, role, content):
        saved.append((username, role, content))

    monkeypatch.setattr(routes_chat, "insert_chat_message", _fake_insert)

    async def _fake_query_groq(system_prompt, user_prompt, history=None):
        assert user_prompt == "¿dónde está el put wall?"
        assert history == [{"role": "user", "content": "hola"}, {"role": "assistant", "content": "hola, en qué te ayudo?"}]
        return "El Put Wall más cercano está en 475."

    monkeypatch.setattr(routes_chat, "query_groq", _fake_query_groq)

    resp = authed_client.post("/chat/message", json={"symbol": "QQQ", "message": "¿dónde está el put wall?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "groq"
    assert body["content"] == "El Put Wall más cercano está en 475."

    assert saved[0] == ("trader1", "user", "¿dónde está el put wall?")
    assert saved[1] == ("trader1", "assistant", "El Put Wall más cercano está en 475.")


def test_post_chat_message_falls_back_to_local_when_groq_unavailable(authed_client, monkeypatch):
    monkeypatch.setattr(ai_context.feed_registry, "get", lambda symbol: _FakeFeed())
    monkeypatch.setattr(ai_context, "fetch_price_history", _fake_candles)
    monkeypatch.setattr(ai_context, "fetch_vix", _fake_vix)

    async def _fake_fetch_chat_history(username, limit=50):
        return []

    monkeypatch.setattr(routes_chat, "fetch_chat_history", _fake_fetch_chat_history)

    async def _fake_insert(username, role, content):
        pass

    monkeypatch.setattr(routes_chat, "insert_chat_message", _fake_insert)

    async def _fake_query_groq_none(system_prompt, user_prompt, history=None):
        return None

    monkeypatch.setattr(routes_chat, "query_groq", _fake_query_groq_none)

    resp = authed_client.post("/chat/message", json={"symbol": "QQQ", "message": "análisis rápido"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "local"
    assert "Resumen Rápido" in body["content"]
