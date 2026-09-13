import asyncio
import time as time_module

import httpx
import pytest

from app.integrations import marketdata_client
from app.integrations.marketdata_client import fetch_oi_map


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://api.marketdata.app/v1/options/chain/VIX/")
            raise httpx.HTTPStatusError("boom", request=request, response=httpx.Response(self.status_code, request=request))

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *args, **kwargs):
        return self._response


class _FakeSettings:
    def __init__(self, marketdata_api_key: str = "fake-key"):
        self.marketdata_api_key = marketdata_api_key


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    marketdata_client._cache.clear()
    marketdata_client._last_attempt.clear()
    marketdata_client._locks.clear()
    monkeypatch.setattr(marketdata_client, "get_settings", lambda: _FakeSettings())
    # Los tests de este archivo, salvo los que prueban el gate de fin de
    # semana explícitamente, asumen un día hábil -- sin esto, corrieron
    # (y fallaron) distinto según qué día real fuera al ejecutar la suite.
    monkeypatch.setattr(marketdata_client, "_is_weekend_ny", lambda: False)


def _patch_response(monkeypatch, response: _FakeResponse):
    monkeypatch.setattr(marketdata_client.httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient(response))


def test_fetch_oi_map_skips_network_on_weekend_no_cache(monkeypatch):
    monkeypatch.setattr(marketdata_client, "_is_weekend_ny", lambda: True)
    calls = {"count": 0}
    monkeypatch.setattr(marketdata_client.httpx, "AsyncClient", lambda **kwargs: calls.__setitem__("count", calls["count"] + 1))

    result = asyncio.run(fetch_oi_map("VIX"))

    assert result is None
    assert calls["count"] == 0


def test_fetch_oi_map_skips_network_on_weekend_returns_stale_cache(monkeypatch):
    # Sábado/domingo: el OI de la última sesión sigue siendo válido (el
    # mercado no abre), así que se devuelve el cache aunque esté "vencido"
    # por REFRESH_INTERVAL_SECONDS, sin gastar cuota pidiéndolo de nuevo.
    stale_map = {(15.0, "call"): 100}
    marketdata_client._cache["VIX"] = (0.0, stale_map)
    monkeypatch.setattr(marketdata_client, "_is_weekend_ny", lambda: True)
    calls = {"count": 0}
    monkeypatch.setattr(marketdata_client.httpx, "AsyncClient", lambda **kwargs: calls.__setitem__("count", calls["count"] + 1))

    result = asyncio.run(fetch_oi_map("VIX"))

    assert result == stale_map
    assert calls["count"] == 0


def test_fetch_oi_map_hits_network_on_weekday(monkeypatch):
    monkeypatch.setattr(marketdata_client, "_is_weekend_ny", lambda: False)
    payload = {"s": "ok", "strike": [15.0], "side": ["call"], "openInterest": [100]}
    _patch_response(monkeypatch, _FakeResponse(200, payload))

    result = asyncio.run(fetch_oi_map("VIX"))

    assert result == {(15.0, "call"): 100}


def test_fetch_oi_map_force_bypasses_weekend_gate(monkeypatch):
    # /market/refresh-oi y oi_scheduler.py usan force=True a propósito
    # para poder refrescar aunque sea fin de semana (ej. alguien lo pide
    # a mano) o aunque el cache todavía esté "fresco".
    monkeypatch.setattr(marketdata_client, "_is_weekend_ny", lambda: True)
    payload = {"s": "ok", "strike": [15.0], "side": ["call"], "openInterest": [100]}
    _patch_response(monkeypatch, _FakeResponse(200, payload))

    result = asyncio.run(fetch_oi_map("VIX", force=True))

    assert result == {(15.0, "call"): 100}


def test_fetch_oi_map_force_bypasses_fresh_cache(monkeypatch):
    monkeypatch.setattr(marketdata_client, "_is_weekend_ny", lambda: False)
    marketdata_client._cache["VIX"] = (time_module.time(), {(10.0, "call"): 1})
    payload = {"s": "ok", "strike": [15.0], "side": ["call"], "openInterest": [100]}
    _patch_response(monkeypatch, _FakeResponse(200, payload))

    result = asyncio.run(fetch_oi_map("VIX", force=True))

    assert result == {(15.0, "call"): 100}


def test_fetch_oi_map_force_still_respects_failure_cooldown(monkeypatch):
    # force=True no debe abrir la puerta a ráfagas de requests -- el
    # cooldown de fallos sigue aplicando incluso con force.
    monkeypatch.setattr(marketdata_client, "_is_weekend_ny", lambda: False)
    marketdata_client._last_attempt["VIX"] = time_module.time()
    calls = {"count": 0}
    monkeypatch.setattr(marketdata_client.httpx, "AsyncClient", lambda **kwargs: calls.__setitem__("count", calls["count"] + 1))

    result = asyncio.run(fetch_oi_map("VIX", force=True))

    assert calls["count"] == 0
    assert result is None


def test_fetch_oi_map_returns_none_without_api_key(monkeypatch):
    monkeypatch.setattr(marketdata_client, "get_settings", lambda: _FakeSettings(marketdata_api_key=""))
    result = asyncio.run(fetch_oi_map("VIX"))
    assert result is None


def test_fetch_oi_map_success_builds_strike_side_map(monkeypatch):
    payload = {"s": "ok", "strike": [15.0, 15.0], "side": ["call", "put"], "openInterest": [100, 50]}
    _patch_response(monkeypatch, _FakeResponse(200, payload))
    result = asyncio.run(fetch_oi_map("VIX"))
    assert result == {(15.0, "call"): 100, (15.0, "put"): 50}


def test_fetch_oi_map_failure_returns_none_without_cache(monkeypatch):
    _patch_response(monkeypatch, _FakeResponse(429))
    result = asyncio.run(fetch_oi_map("VIX"))
    assert result is None


def test_fetch_oi_map_failure_does_not_retry_within_cooldown(monkeypatch):
    """Regresión del bug real visto en producción: un 429 dejaba el caché
    vacío, así que CADA tick de 2s reintentaba de inmediato -- un bucle
    que nunca le daba tiempo a MarketData.app para levantar el rate limit.
    Con el cooldown, un segundo intento inmediato no debe golpear la red
    de nuevo."""
    calls = {"count": 0}

    class _CountingClient(_FakeAsyncClient):
        async def get(self, *args, **kwargs):
            calls["count"] += 1
            return self._response

    monkeypatch.setattr(marketdata_client.httpx, "AsyncClient", lambda **kwargs: _CountingClient(_FakeResponse(429)))

    asyncio.run(fetch_oi_map("VIX"))
    asyncio.run(fetch_oi_map("VIX"))
    assert calls["count"] == 1


def test_fetch_oi_map_keeps_previous_cache_on_new_failure(monkeypatch):
    ok_payload = {"s": "ok", "strike": [15.0], "side": ["call"], "openInterest": [100]}
    _patch_response(monkeypatch, _FakeResponse(200, ok_payload))
    first = asyncio.run(fetch_oi_map("VIX"))
    assert first == {(15.0, "call"): 100}

    # Fuerza que el próximo intento no esté bloqueado por REFRESH_INTERVAL
    # ni por el cooldown de fallos, simulando que ya pasó tiempo real.
    marketdata_client._cache["VIX"] = (0.0, first)
    marketdata_client._last_attempt["VIX"] = 0.0
    _patch_response(monkeypatch, _FakeResponse(429))
    second = asyncio.run(fetch_oi_map("VIX"))
    assert second == {(15.0, "call"): 100}
