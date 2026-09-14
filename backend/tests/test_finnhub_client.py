import asyncio

import httpx
import pytest

from app.integrations import finnhub_client
from app.integrations.finnhub_client import fetch_market_news


class _FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        # 'payload if payload is not None else {}' (NO 'payload or {}') --
        # una lista vacía [] es un payload válido (Finnhub devuelve una
        # lista JSON directa, no un dict envolvente) y es falsy en
        # Python, así que 'or {}' la pisaba en silencio.
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://finnhub.io/api/v1/news")
            raise httpx.HTTPStatusError("boom", request=request, response=httpx.Response(self.status_code, request=request))

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response=None, exc: Exception | None = None):
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *args, **kwargs):
        if self._exc:
            raise self._exc
        return self._response


class _FakeSettings:
    def __init__(self, finnhub_api_key: str = "fake-key"):
        self.finnhub_api_key = finnhub_api_key


@pytest.fixture(autouse=True)
def _reset_module_state():
    finnhub_client._cache.clear()
    finnhub_client._last_attempt = 0.0


def test_fetch_market_news_returns_empty_without_api_key(monkeypatch):
    monkeypatch.setattr(finnhub_client, "get_settings", lambda: _FakeSettings(finnhub_api_key=""))
    result = asyncio.run(fetch_market_news())
    assert result == []


def test_fetch_market_news_returns_empty_on_network_failure(monkeypatch):
    monkeypatch.setattr(finnhub_client, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(
        finnhub_client.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(exc=httpx.ConnectError("boom")),
    )
    result = asyncio.run(fetch_market_news())
    assert result == []


def test_fetch_market_news_parses_and_sorts_newest_first(monkeypatch):
    monkeypatch.setattr(finnhub_client, "get_settings", lambda: _FakeSettings())
    payload = [
        {"headline": "Older headline", "summary": "s1", "url": "https://a", "source": "Reuters", "datetime": 100, "image": ""},
        {"headline": "Newer headline", "summary": "s2", "url": "https://b", "source": "Bloomberg", "datetime": 200, "image": ""},
        {"headline": "", "summary": "sin titulo, se descarta", "url": "https://c", "source": "X", "datetime": 300, "image": ""},
    ]
    monkeypatch.setattr(
        finnhub_client.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(response=_FakeResponse(200, payload)),
    )

    result = asyncio.run(fetch_market_news())

    assert [a["headline"] for a in result] == ["Newer headline", "Older headline"]  # más reciente primero, sin la vacía


def test_fetch_market_news_caches_within_ttl(monkeypatch):
    monkeypatch.setattr(finnhub_client, "get_settings", lambda: _FakeSettings())
    calls = {"count": 0}

    def _fake_async_client(*a, **kw):
        calls["count"] += 1
        return _FakeAsyncClient(response=_FakeResponse(200, []))

    monkeypatch.setattr(finnhub_client.httpx, "AsyncClient", _fake_async_client)

    asyncio.run(fetch_market_news())
    asyncio.run(fetch_market_news())

    assert calls["count"] == 1


def test_fetch_market_news_does_not_retry_immediately_after_a_failure(monkeypatch):
    # Mismo patrón ya probado en marketdata_client.py/forexfactory_client.py,
    # que faltaba acá -- sin cooldown, cada apertura de la pestaña News
    # durante una caída sostenida de Finnhub reintenta sin ningún backoff.
    monkeypatch.setattr(finnhub_client, "get_settings", lambda: _FakeSettings())
    calls = {"count": 0}

    def _fake_async_client(*a, **kw):
        calls["count"] += 1
        return _FakeAsyncClient(exc=httpx.ConnectError("boom"))

    monkeypatch.setattr(finnhub_client.httpx, "AsyncClient", _fake_async_client)

    asyncio.run(fetch_market_news())
    asyncio.run(fetch_market_news())

    assert calls["count"] == 1


def test_fetch_market_news_retries_after_cooldown_elapses(monkeypatch):
    monkeypatch.setattr(finnhub_client, "get_settings", lambda: _FakeSettings())
    calls = {"count": 0}

    def _fake_async_client(*a, **kw):
        calls["count"] += 1
        return _FakeAsyncClient(exc=httpx.ConnectError("boom"))

    monkeypatch.setattr(finnhub_client.httpx, "AsyncClient", _fake_async_client)

    asyncio.run(fetch_market_news())
    finnhub_client._last_attempt -= finnhub_client.FAILURE_COOLDOWN_SECONDS + 1
    asyncio.run(fetch_market_news())

    assert calls["count"] == 2
