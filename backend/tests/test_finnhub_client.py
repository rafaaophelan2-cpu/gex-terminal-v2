import asyncio

import httpx
import pytest

from app.integrations import finnhub_client
from app.integrations.finnhub_client import fetch_economic_calendar, fetch_market_news


class _FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        # 'payload if payload is not None else {}' (NO 'payload or {}') --
        # una lista vacía [] es un payload válido (ver fetch_market_news,
        # Finnhub devuelve una lista JSON directa, no un dict envolvente)
        # y es falsy en Python, así que 'or {}' la pisaba en silencio.
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://finnhub.io/api/v1/calendar/economic")
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


def test_fetch_economic_calendar_returns_empty_without_api_key(monkeypatch):
    monkeypatch.setattr(finnhub_client, "get_settings", lambda: _FakeSettings(finnhub_api_key=""))
    result = asyncio.run(fetch_economic_calendar())
    assert result == []


def test_fetch_economic_calendar_returns_empty_on_network_failure(monkeypatch):
    monkeypatch.setattr(finnhub_client, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(
        finnhub_client.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(exc=httpx.ConnectError("boom")),
    )
    result = asyncio.run(fetch_economic_calendar())
    assert result == []


def test_fetch_economic_calendar_filters_to_us_medium_high_impact_today(monkeypatch):
    monkeypatch.setattr(finnhub_client, "get_settings", lambda: _FakeSettings())

    today_str = finnhub_client.datetime.now(finnhub_client.NY_TZ).date().isoformat()
    payload = {
        "economicCalendar": [
            {"country": "US", "impact": "high", "event": "CPI m/m", "time": f"{today_str} 08:30:00", "actual": None, "estimate": "0.3", "prev": "0.2"},
            {"country": "US", "impact": "low", "event": "Bond Auction", "time": f"{today_str} 11:00:00", "actual": None, "estimate": None, "prev": None},
            {"country": "DE", "impact": "high", "event": "German ZEW", "time": f"{today_str} 05:00:00", "actual": None, "estimate": None, "prev": None},
            {"country": "US", "impact": "medium", "event": "ISM Services PMI", "time": f"{today_str} 10:00:00", "actual": "54.2", "estimate": "54.1", "prev": "54.0"},
        ],
    }
    monkeypatch.setattr(
        finnhub_client.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(response=_FakeResponse(200, payload)),
    )

    result = asyncio.run(fetch_economic_calendar())

    assert [e["event"] for e in result] == ["CPI m/m", "ISM Services PMI"]  # ordenado por hora, sin low impact ni DE
    assert result[0] == {
        "date": today_str, "time": "08:30", "event": "CPI m/m", "impact": "high",
        "actual": None, "forecast": "0.3", "previous": "0.2",
    }


def test_fetch_economic_calendar_days_ahead_includes_future_days(monkeypatch):
    monkeypatch.setattr(finnhub_client, "get_settings", lambda: _FakeSettings())

    today = finnhub_client.datetime.now(finnhub_client.NY_TZ).date()
    tomorrow = today + finnhub_client.timedelta(days=1)
    after_tomorrow = today + finnhub_client.timedelta(days=2)
    payload = {
        "economicCalendar": [
            {"country": "US", "impact": "high", "event": "Today Event", "time": f"{today.isoformat()} 08:30:00", "actual": None, "estimate": None, "prev": None},
            {"country": "US", "impact": "high", "event": "Tomorrow Event", "time": f"{tomorrow.isoformat()} 07:30:00", "actual": None, "estimate": None, "prev": None},
            {"country": "US", "impact": "high", "event": "Day After Event (fuera de rango)", "time": f"{after_tomorrow.isoformat()} 07:30:00", "actual": None, "estimate": None, "prev": None},
        ],
    }
    monkeypatch.setattr(
        finnhub_client.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(response=_FakeResponse(200, payload)),
    )

    result = asyncio.run(fetch_economic_calendar(days_ahead=1))

    assert [e["event"] for e in result] == ["Today Event", "Tomorrow Event"]
    assert result[1]["date"] == tomorrow.isoformat()


def test_fetch_economic_calendar_days_ahead_zero_matches_default(monkeypatch):
    # días_ahead=0 (default, usado por el prompt de la IA) no debe traer
    # ningún evento de mañana, ni con days_ahead explícito en 0.
    monkeypatch.setattr(finnhub_client, "get_settings", lambda: _FakeSettings())
    today = finnhub_client.datetime.now(finnhub_client.NY_TZ).date()
    tomorrow = today + finnhub_client.timedelta(days=1)
    payload = {
        "economicCalendar": [
            {"country": "US", "impact": "high", "event": "Today Event", "time": f"{today.isoformat()} 08:30:00", "actual": None, "estimate": None, "prev": None},
            {"country": "US", "impact": "high", "event": "Tomorrow Event", "time": f"{tomorrow.isoformat()} 07:30:00", "actual": None, "estimate": None, "prev": None},
        ],
    }
    monkeypatch.setattr(
        finnhub_client.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(response=_FakeResponse(200, payload)),
    )

    result = asyncio.run(fetch_economic_calendar(days_ahead=0))

    assert [e["event"] for e in result] == ["Today Event"]


def test_fetch_economic_calendar_caches_within_the_same_day(monkeypatch):
    monkeypatch.setattr(finnhub_client, "get_settings", lambda: _FakeSettings())
    calls = {"count": 0}

    def _fake_async_client(*a, **kw):
        calls["count"] += 1
        return _FakeAsyncClient(response=_FakeResponse(200, {"economicCalendar": []}))

    monkeypatch.setattr(finnhub_client.httpx, "AsyncClient", _fake_async_client)

    asyncio.run(fetch_economic_calendar())
    asyncio.run(fetch_economic_calendar())

    assert calls["count"] == 1


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
