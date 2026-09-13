import asyncio
from datetime import date, datetime, tzinfo

import httpx
import pytest

from app.integrations import finnhub_client
from app.integrations.finnhub_client import fetch_economic_calendar, fetch_market_news


class _FixedDatetime(datetime):
    _fixed: "datetime | None" = None

    @classmethod
    def now(cls, tz: tzinfo | None = None):
        return cls._fixed if tz is None else cls._fixed.astimezone(tz)


def _install_fixed_now(monkeypatch, fixed: datetime):
    _FixedDatetime._fixed = fixed
    monkeypatch.setattr(finnhub_client, "datetime", _FixedDatetime)


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


def test_relevant_week_range_weekday_returns_current_week():
    # Miércoles 2026-09-09 -> semana actual: lunes 07 a domingo 13.
    monday, sunday = finnhub_client._relevant_week_range(date(2026, 9, 9))
    assert monday == date(2026, 9, 7)
    assert sunday == date(2026, 9, 13)


def test_relevant_week_range_friday_still_returns_current_week():
    monday, sunday = finnhub_client._relevant_week_range(date(2026, 9, 11))
    assert monday == date(2026, 9, 7)
    assert sunday == date(2026, 9, 13)


def test_relevant_week_range_saturday_rolls_to_next_week():
    # Sábado -- pedido explícito del usuario: no tiene sentido mostrar una
    # semana que ya terminó, se muestra la SIGUIENTE.
    monday, sunday = finnhub_client._relevant_week_range(date(2026, 9, 12))
    assert monday == date(2026, 9, 14)
    assert sunday == date(2026, 9, 20)


def test_relevant_week_range_sunday_rolls_to_next_week():
    monday, sunday = finnhub_client._relevant_week_range(date(2026, 9, 13))
    assert monday == date(2026, 9, 14)
    assert sunday == date(2026, 9, 20)


def test_fetch_economic_calendar_includes_all_three_impact_levels_and_excludes_other_countries(monkeypatch):
    monkeypatch.setattr(finnhub_client, "get_settings", lambda: _FakeSettings())
    _install_fixed_now(monkeypatch, datetime(2026, 9, 9, 12, 0, tzinfo=finnhub_client.NY_TZ))  # miércoles

    payload = {
        "economicCalendar": [
            {"country": "US", "impact": "high", "event": "CPI m/m", "time": "2026-09-09 08:30:00", "actual": None, "estimate": "0.3", "prev": "0.2"},
            {"country": "US", "impact": "low", "event": "Bond Auction", "time": "2026-09-09 11:00:00", "actual": None, "estimate": None, "prev": None},
            {"country": "DE", "impact": "high", "event": "German ZEW", "time": "2026-09-09 05:00:00", "actual": None, "estimate": None, "prev": None},
            {"country": "US", "impact": "medium", "event": "ISM Services PMI", "time": "2026-09-09 10:00:00", "actual": "54.2", "estimate": "54.1", "prev": "54.0"},
        ],
    }
    monkeypatch.setattr(
        finnhub_client.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(response=_FakeResponse(200, payload)),
    )

    result = asyncio.run(fetch_economic_calendar())

    # 'low' AHORA se incluye (pedido explícito: 3 símbolos de color en vez
    # de descartarlo), 'DE' (no US) sigue afuera. Ordenado por hora.
    assert [e["event"] for e in result] == ["CPI m/m", "ISM Services PMI", "Bond Auction"]
    assert result[0] == {
        "date": "2026-09-09", "time": "08:30", "event": "CPI m/m", "impact": "high",
        "actual": None, "forecast": "0.3", "previous": "0.2",
    }
    assert result[2]["impact"] == "low"


def test_fetch_economic_calendar_covers_the_whole_week_monday_to_sunday(monkeypatch):
    monkeypatch.setattr(finnhub_client, "get_settings", lambda: _FakeSettings())
    _install_fixed_now(monkeypatch, datetime(2026, 9, 9, 12, 0, tzinfo=finnhub_client.NY_TZ))  # miércoles -> semana 07-13

    payload = {
        "economicCalendar": [
            {"country": "US", "impact": "high", "event": "Monday Event (ya paso, sigue incluido)", "time": "2026-09-07 08:30:00", "actual": "1.0", "estimate": "1.0", "prev": "0.9"},
            {"country": "US", "impact": "high", "event": "Sunday Event (borde final de la semana)", "time": "2026-09-13 08:30:00", "actual": None, "estimate": None, "prev": None},
            {"country": "US", "impact": "high", "event": "Next Monday Event (fuera de rango)", "time": "2026-09-14 08:30:00", "actual": None, "estimate": None, "prev": None},
            {"country": "US", "impact": "high", "event": "Prev Sunday Event (fuera de rango)", "time": "2026-09-06 08:30:00", "actual": None, "estimate": None, "prev": None},
        ],
    }
    monkeypatch.setattr(
        finnhub_client.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(response=_FakeResponse(200, payload)),
    )

    result = asyncio.run(fetch_economic_calendar())

    assert [e["event"] for e in result] == [
        "Monday Event (ya paso, sigue incluido)",
        "Sunday Event (borde final de la semana)",
    ]


def test_fetch_economic_calendar_on_weekend_shows_next_week(monkeypatch):
    monkeypatch.setattr(finnhub_client, "get_settings", lambda: _FakeSettings())
    _install_fixed_now(monkeypatch, datetime(2026, 9, 12, 10, 0, tzinfo=finnhub_client.NY_TZ))  # sábado -> semana 14-20

    payload = {
        "economicCalendar": [
            {"country": "US", "impact": "high", "event": "This Week Event (fuera de rango, ya paso)", "time": "2026-09-09 08:30:00", "actual": None, "estimate": None, "prev": None},
            {"country": "US", "impact": "high", "event": "Next Week Event", "time": "2026-09-16 08:30:00", "actual": None, "estimate": None, "prev": None},
        ],
    }
    monkeypatch.setattr(
        finnhub_client.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(response=_FakeResponse(200, payload)),
    )

    result = asyncio.run(fetch_economic_calendar())

    assert [e["event"] for e in result] == ["Next Week Event"]


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
