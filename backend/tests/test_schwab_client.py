import asyncio

import pytest

from app.integrations import schwab_client


class _FakeSettings:
    def __init__(self, schwab_client_id: str = "id", schwab_client_secret: str = "secret"):
        self.schwab_client_id = schwab_client_id
        self.schwab_client_secret = schwab_client_secret


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    schwab_client._cached_schwab_client = None
    schwab_client._client_init_last_attempt = 0.0
    schwab_client._last_good.clear()
    schwab_client._last_failure_attempt.clear()
    monkeypatch.setattr(schwab_client, "settings", _FakeSettings())


def test_get_schwab_client_returns_none_without_credentials(monkeypatch):
    monkeypatch.setattr(schwab_client, "settings", _FakeSettings(schwab_client_id="", schwab_client_secret=""))
    assert schwab_client.get_schwab_client() is None


def test_get_schwab_client_retries_after_cooldown_when_no_token_yet(monkeypatch):
    # Bug real: @lru_cache sobre esta función memorizaba CUALQUIER
    # resultado para siempre, incluido None -- si se llamaba una vez antes
    # de que existiera el token en Supabase, quedaba en None de por vida
    # del proceso, y correr bootstrap_schwab_token.py después no tenía
    # ningún efecto sin un restart manual. Ahora debe reintentar solo
    # (con cooldown) en vez de quedar fijo para siempre.
    calls = {"count": 0}

    def _fake_read_token():
        calls["count"] += 1
        return None  # todavía no hay token en Supabase

    monkeypatch.setattr(schwab_client, "_read_token_sync", _fake_read_token)
    monkeypatch.setattr(schwab_client, "client_from_access_functions", lambda **kwargs: "fake-client")

    first = schwab_client.get_schwab_client()
    assert first is None
    assert calls["count"] == 1

    # Dentro del cooldown -- no debe volver a intentar leer el token.
    second = schwab_client.get_schwab_client()
    assert second is None
    assert calls["count"] == 1

    # Cooldown vencido (simulado retrocediendo el timestamp del último
    # intento) -- ahora el token SÍ está disponible, debe reintentar y
    # esta vez crear el cliente con éxito.
    schwab_client._client_init_last_attempt -= schwab_client.CLIENT_INIT_COOLDOWN_SECONDS + 1

    def _fake_read_token_now_available():
        calls["count"] += 1
        return {"token": "real"}

    monkeypatch.setattr(schwab_client, "_read_token_sync", _fake_read_token_now_available)
    third = schwab_client.get_schwab_client()
    assert third == "fake-client"
    assert calls["count"] == 2


def test_get_schwab_client_caches_successful_client_permanently(monkeypatch):
    calls = {"count": 0}

    def _fake_read_token():
        calls["count"] += 1
        return {"token": "real"}

    monkeypatch.setattr(schwab_client, "_read_token_sync", _fake_read_token)
    monkeypatch.setattr(schwab_client, "client_from_access_functions", lambda **kwargs: object())

    client1 = schwab_client.get_schwab_client()
    client2 = schwab_client.get_schwab_client()
    assert client1 is client2
    assert calls["count"] == 1  # el segundo llamado usó el cache, no volvió a leer Supabase


def test_call_with_fallback_does_not_retry_immediately_after_a_failure():
    calls = {"count": 0}

    async def _failing_fetch():
        calls["count"] += 1
        raise RuntimeError("Schwab caído")

    async def _run_twice():
        await schwab_client.call_with_fallback("k", "empty", _failing_fetch)
        return await schwab_client.call_with_fallback("k", "empty", _failing_fetch)

    result = asyncio.run(_run_twice())
    assert result == "empty"
    assert calls["count"] == 1  # el segundo intento fue bloqueado por el cooldown


def test_call_with_fallback_retries_after_cooldown_elapses():
    calls = {"count": 0}

    async def _failing_fetch():
        calls["count"] += 1
        raise RuntimeError("Schwab caído")

    asyncio.run(schwab_client.call_with_fallback("k", "empty", _failing_fetch))
    schwab_client._last_failure_attempt["k"] -= schwab_client.FAILURE_COOLDOWN_SECONDS + 1
    asyncio.run(schwab_client.call_with_fallback("k", "empty", _failing_fetch))

    assert calls["count"] == 2


def test_call_with_fallback_empty_result_does_not_trigger_cooldown():
    # Un resultado "vacío" (sin excepción) puede ser real y momentáneo
    # (ej. el mercado no abrió todavía) -- no debe bloquear el próximo
    # intento como sí lo hace un fallo real.
    calls = {"count": 0}

    async def _empty_fetch():
        calls["count"] += 1
        return {}

    async def _run_twice():
        await schwab_client.call_with_fallback("k", "empty", _empty_fetch)
        return await schwab_client.call_with_fallback("k", "empty", _empty_fetch)

    asyncio.run(_run_twice())
    assert calls["count"] == 2
