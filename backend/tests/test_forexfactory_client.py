import asyncio
from datetime import date, datetime, tzinfo

import httpx
import pytest

from app.integrations import forexfactory_client
from app.integrations.forexfactory_client import fetch_economic_calendar


class _FixedDatetime(datetime):
    _fixed: "datetime | None" = None

    @classmethod
    def now(cls, tz: tzinfo | None = None):
        return cls._fixed if tz is None else cls._fixed.astimezone(tz)


def _install_fixed_now(monkeypatch, fixed: datetime):
    _FixedDatetime._fixed = fixed
    monkeypatch.setattr(forexfactory_client, "datetime", _FixedDatetime)


class _FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else []

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", forexfactory_client.THISWEEK_URL)
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


@pytest.fixture(autouse=True)
def _reset_module_state():
    forexfactory_client._cache.clear()
    forexfactory_client._last_attempt = 0.0


def test_relevant_week_range_weekday_returns_current_week():
    # Miércoles 2026-09-09 -> semana actual: lunes 07 a domingo 13.
    monday, sunday = forexfactory_client._relevant_week_range(date(2026, 9, 9))
    assert monday == date(2026, 9, 7)
    assert sunday == date(2026, 9, 13)


def test_relevant_week_range_friday_still_returns_current_week():
    monday, sunday = forexfactory_client._relevant_week_range(date(2026, 9, 11))
    assert monday == date(2026, 9, 7)
    assert sunday == date(2026, 9, 13)


def test_relevant_week_range_saturday_rolls_to_next_week():
    # Sábado -- pedido explícito del usuario: no tiene sentido mostrar una
    # semana que ya terminó, se muestra la SIGUIENTE.
    monday, sunday = forexfactory_client._relevant_week_range(date(2026, 9, 12))
    assert monday == date(2026, 9, 14)
    assert sunday == date(2026, 9, 20)


def test_relevant_week_range_sunday_rolls_to_next_week():
    monday, sunday = forexfactory_client._relevant_week_range(date(2026, 9, 13))
    assert monday == date(2026, 9, 14)
    assert sunday == date(2026, 9, 20)


def test_fetch_economic_calendar_returns_empty_on_network_failure(monkeypatch):
    _install_fixed_now(monkeypatch, datetime(2026, 9, 9, 12, 0, tzinfo=forexfactory_client.NY_TZ))
    monkeypatch.setattr(
        forexfactory_client.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(exc=httpx.ConnectError("boom")),
    )
    result = asyncio.run(fetch_economic_calendar())
    assert result == []


def test_fetch_economic_calendar_filters_usd_and_includes_all_three_impact_levels(monkeypatch):
    _install_fixed_now(monkeypatch, datetime(2026, 9, 9, 12, 0, tzinfo=forexfactory_client.NY_TZ))  # miércoles

    payload = [
        {"title": "CPI m/m", "country": "USD", "date": "2026-09-09T08:30:00-04:00", "impact": "High", "forecast": "0.3%", "previous": "0.2%"},
        {"title": "Minor Data", "country": "USD", "date": "2026-09-09T11:00:00-04:00", "impact": "Low", "forecast": "", "previous": ""},
        {"title": "German ZEW", "country": "EUR", "date": "2026-09-09T05:00:00-04:00", "impact": "High", "forecast": "", "previous": ""},
        {"title": "ISM Services PMI", "country": "USD", "date": "2026-09-09T10:00:00-04:00", "impact": "Medium", "forecast": "54.1", "previous": "54.0"},
        {"title": "Bank Holiday", "country": "USD", "date": "2026-09-09T00:00:00-04:00", "impact": "Holiday", "forecast": "", "previous": ""},
    ]
    monkeypatch.setattr(
        forexfactory_client.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(response=_FakeResponse(200, payload)),
    )

    result = asyncio.run(fetch_economic_calendar())

    # 'EUR' (no USD) y 'Holiday' quedan afuera. Ordenado por hora.
    assert [e["event"] for e in result] == ["CPI m/m", "ISM Services PMI", "Minor Data"]
    assert result[0] == {
        "date": "2026-09-09", "time": "08:30", "event": "CPI m/m", "impact": "high",
        "actual": None, "forecast": "0.3%", "previous": "0.2%",
    }
    assert result[2]["impact"] == "low"


def test_fetch_economic_calendar_covers_the_whole_week_monday_to_sunday(monkeypatch):
    _install_fixed_now(monkeypatch, datetime(2026, 9, 9, 12, 0, tzinfo=forexfactory_client.NY_TZ))  # miércoles -> semana 07-13

    payload = [
        {"title": "Monday Event (ya paso, sigue incluido)", "country": "USD", "date": "2026-09-07T08:30:00-04:00", "impact": "High", "forecast": "1.0", "previous": "0.9"},
        {"title": "Sunday Event (borde final de la semana)", "country": "USD", "date": "2026-09-13T08:30:00-04:00", "impact": "High", "forecast": "", "previous": ""},
        {"title": "Next Monday Event (fuera de rango)", "country": "USD", "date": "2026-09-14T08:30:00-04:00", "impact": "High", "forecast": "", "previous": ""},
        {"title": "Prev Sunday Event (fuera de rango)", "country": "USD", "date": "2026-09-06T08:30:00-04:00", "impact": "High", "forecast": "", "previous": ""},
    ]
    monkeypatch.setattr(
        forexfactory_client.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(response=_FakeResponse(200, payload)),
    )

    result = asyncio.run(fetch_economic_calendar())

    assert [e["event"] for e in result] == [
        "Monday Event (ya paso, sigue incluido)",
        "Sunday Event (borde final de la semana)",
    ]


def test_fetch_economic_calendar_on_weekend_shows_next_week(monkeypatch):
    _install_fixed_now(monkeypatch, datetime(2026, 9, 12, 10, 0, tzinfo=forexfactory_client.NY_TZ))  # sábado -> semana 14-20

    payload = [
        {"title": "This Week Event (fuera de rango, ya paso)", "country": "USD", "date": "2026-09-09T08:30:00-04:00", "impact": "High", "forecast": "", "previous": ""},
        {"title": "Next Week Event", "country": "USD", "date": "2026-09-16T08:30:00-04:00", "impact": "High", "forecast": "", "previous": ""},
    ]
    monkeypatch.setattr(
        forexfactory_client.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(response=_FakeResponse(200, payload)),
    )

    result = asyncio.run(fetch_economic_calendar())

    assert [e["event"] for e in result] == ["Next Week Event"]


def test_fetch_economic_calendar_uses_actual_field_when_published(monkeypatch):
    _install_fixed_now(monkeypatch, datetime(2026, 9, 9, 12, 0, tzinfo=forexfactory_client.NY_TZ))
    payload = [
        {"title": "CPI m/m", "country": "USD", "date": "2026-09-09T08:30:00-04:00", "impact": "High", "actual": "0.4%", "forecast": "0.3%", "previous": "0.2%"},
    ]
    monkeypatch.setattr(
        forexfactory_client.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(response=_FakeResponse(200, payload)),
    )

    result = asyncio.run(fetch_economic_calendar())
    assert result[0]["actual"] == "0.4%"


def test_fetch_raw_week_caches_within_ttl(monkeypatch):
    _install_fixed_now(monkeypatch, datetime(2026, 9, 9, 12, 0, tzinfo=forexfactory_client.NY_TZ))
    calls = {"count": 0}

    def _fake_async_client(*a, **kw):
        calls["count"] += 1
        return _FakeAsyncClient(response=_FakeResponse(200, []))

    monkeypatch.setattr(forexfactory_client.httpx, "AsyncClient", _fake_async_client)

    asyncio.run(fetch_economic_calendar())
    asyncio.run(fetch_economic_calendar())

    assert calls["count"] == 1


def test_fetch_raw_week_does_not_retry_immediately_after_a_failure(monkeypatch):
    # Bug real confirmado en vivo en Render (13-sep-2026): un solo 429 de
    # ForexFactory dejaba _cache sin actualizar, así que CADA pedido
    # siguiente reintentaba de inmediato y volvía a pisar el rate limit
    # externo (2 req/5 min) -- nunca se recuperaba solo. FAILURE_COOLDOWN_SECONDS
    # evita ese reintento inmediato.
    _install_fixed_now(monkeypatch, datetime(2026, 9, 9, 12, 0, tzinfo=forexfactory_client.NY_TZ))
    calls = {"count": 0}

    def _fake_async_client(*a, **kw):
        calls["count"] += 1
        return _FakeAsyncClient(exc=httpx.ConnectError("boom"))

    monkeypatch.setattr(forexfactory_client.httpx, "AsyncClient", _fake_async_client)

    asyncio.run(fetch_economic_calendar())
    asyncio.run(fetch_economic_calendar())
    asyncio.run(fetch_economic_calendar())

    assert calls["count"] == 1  # el primer fallo activa el cooldown -- los siguientes ni intentan la red


def test_fetch_raw_week_retries_after_cooldown_elapses(monkeypatch):
    _install_fixed_now(monkeypatch, datetime(2026, 9, 9, 12, 0, tzinfo=forexfactory_client.NY_TZ))
    calls = {"count": 0}

    def _fake_async_client(*a, **kw):
        calls["count"] += 1
        return _FakeAsyncClient(exc=httpx.ConnectError("boom"))

    monkeypatch.setattr(forexfactory_client.httpx, "AsyncClient", _fake_async_client)

    asyncio.run(fetch_economic_calendar())
    assert calls["count"] == 1

    # Simula que ya pasó el cooldown corriendo el reloj hacia adelante.
    forexfactory_client._last_attempt -= forexfactory_client.FAILURE_COOLDOWN_SECONDS + 1

    asyncio.run(fetch_economic_calendar())
    assert calls["count"] == 2


def test_fetch_raw_week_falls_back_to_supabase_when_live_fetch_fails(monkeypatch):
    # Bug real confirmado en vivo (14-sep-2026): el Cache API de
    # Cloudflare es POR PoP, no global -- el backend puede seguir
    # recibiendo 429 de ff-calendar.js aunque OTRO PoP ya tenga un
    # fetch reciente cacheado. fetch_cached_economic_calendar() (Supabase)
    # es el fallback que sobrevive esto (y los redeploys).
    _install_fixed_now(monkeypatch, datetime(2026, 9, 9, 12, 0, tzinfo=forexfactory_client.NY_TZ))
    monkeypatch.setattr(
        forexfactory_client.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(exc=httpx.ConnectError("boom")),
    )

    cached_payload = [
        {"title": "CPI m/m", "country": "USD", "date": "2026-09-09T08:30:00-04:00", "impact": "High", "forecast": "", "previous": ""},
    ]

    async def _fake_fetch_cached():
        return cached_payload

    monkeypatch.setattr(forexfactory_client, "fetch_cached_economic_calendar", _fake_fetch_cached)

    result = asyncio.run(fetch_economic_calendar())
    assert [e["event"] for e in result] == ["CPI m/m"]


def test_fetch_raw_week_persists_to_supabase_on_success(monkeypatch):
    _install_fixed_now(monkeypatch, datetime(2026, 9, 9, 12, 0, tzinfo=forexfactory_client.NY_TZ))
    payload = [
        {"title": "CPI m/m", "country": "USD", "date": "2026-09-09T08:30:00-04:00", "impact": "High", "forecast": "", "previous": ""},
    ]
    monkeypatch.setattr(
        forexfactory_client.httpx, "AsyncClient",
        lambda *a, **kw: _FakeAsyncClient(response=_FakeResponse(200, payload)),
    )

    saved = {}

    async def _fake_save(events):
        saved["events"] = events

    monkeypatch.setattr(forexfactory_client, "save_economic_calendar_cache", _fake_save)

    asyncio.run(fetch_economic_calendar())
    assert saved["events"] == payload
