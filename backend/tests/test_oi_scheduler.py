import asyncio
from datetime import datetime

import app.services.oi_scheduler as oi_scheduler


def _install_fake_fetch(monkeypatch, results: dict):
    """results: {symbol: [return_val_call1, return_val_call2, ...]}"""
    calls: list[str] = []

    async def _fake_fetch(symbol, force=False):
        calls.append(symbol)
        queue = results.get(symbol, [])
        return queue.pop(0) if queue else None

    monkeypatch.setattr(oi_scheduler, "fetch_oi_map", _fake_fetch)
    return calls


def test_try_refresh_calls_fetch_and_marks_success(monkeypatch):
    oi_scheduler._last_success_date.clear()
    calls = _install_fake_fetch(monkeypatch, {"VIX": [{(15.0, "call"): 1}]})

    today = datetime(2026, 9, 11).date()
    asyncio.run(oi_scheduler._try_refresh("VIX", today))

    assert calls == ["VIX"]
    assert oi_scheduler._last_success_date["VIX"] == today


def test_try_refresh_skips_if_already_succeeded_today(monkeypatch):
    oi_scheduler._last_success_date.clear()
    today = datetime(2026, 9, 11).date()
    oi_scheduler._last_success_date["VIX"] = today
    calls = _install_fake_fetch(monkeypatch, {"VIX": [{(15.0, "call"): 1}]})

    asyncio.run(oi_scheduler._try_refresh("VIX", today))

    # No debe volver a llamar a fetch_oi_map -- ya se consiguió hoy.
    assert calls == []


def test_try_refresh_does_not_mark_success_on_failure(monkeypatch):
    oi_scheduler._last_success_date.clear()
    calls = _install_fake_fetch(monkeypatch, {"VIX": [None]})

    today = datetime(2026, 9, 11).date()
    asyncio.run(oi_scheduler._try_refresh("VIX", today))

    assert calls == ["VIX"]
    assert "VIX" not in oi_scheduler._last_success_date


def test_try_refresh_retries_next_call_after_failure(monkeypatch):
    # Simula dos ciclos del loop: el primero falla, el segundo (mismo día)
    # debe reintentar en vez de quedar marcado como ya resuelto.
    oi_scheduler._last_success_date.clear()
    calls = _install_fake_fetch(monkeypatch, {"VIX": [None, {(15.0, "call"): 1}]})
    today = datetime(2026, 9, 11).date()

    asyncio.run(oi_scheduler._try_refresh("VIX", today))
    asyncio.run(oi_scheduler._try_refresh("VIX", today))

    assert calls == ["VIX", "VIX"]
    assert oi_scheduler._last_success_date["VIX"] == today


def test_try_final_retry_calls_fetch_when_window_failed(monkeypatch):
    # Pedido explícito del usuario: si toda la ventana 09:00-09:30 falló,
    # un intento más ~1 min después de la apertura en vez de quedarse sin
    # OI real el resto del día.
    oi_scheduler._last_success_date.clear()
    oi_scheduler._final_retry_done.clear()
    calls = _install_fake_fetch(monkeypatch, {"VIX": [{(15.0, "call"): 1}]})

    today = datetime(2026, 9, 11).date()
    asyncio.run(oi_scheduler._try_final_retry("VIX", today))

    assert calls == ["VIX"]
    assert oi_scheduler._last_success_date["VIX"] == today
    assert oi_scheduler._final_retry_done["VIX"] == today


def test_try_final_retry_skips_if_window_already_succeeded(monkeypatch):
    oi_scheduler._last_success_date.clear()
    oi_scheduler._final_retry_done.clear()
    today = datetime(2026, 9, 11).date()
    oi_scheduler._last_success_date["VIX"] = today
    calls = _install_fake_fetch(monkeypatch, {"VIX": [{(15.0, "call"): 1}]})

    asyncio.run(oi_scheduler._try_final_retry("VIX", today))

    assert calls == []


def test_try_final_retry_only_fires_once_per_day_even_on_failure(monkeypatch):
    # Aunque el intento final también falle, no debe reintentarse en cada
    # chequeo del loop (cada 60s) dentro de la ventana 09:31-09:35 --
    # queda un único intento, y el resto del día se apoya en el fallback
    # de volumen hasta el próximo refresco por hora.
    oi_scheduler._last_success_date.clear()
    oi_scheduler._final_retry_done.clear()
    calls = _install_fake_fetch(monkeypatch, {"VIX": [None, {(15.0, "call"): 1}]})
    today = datetime(2026, 9, 11).date()

    asyncio.run(oi_scheduler._try_final_retry("VIX", today))
    asyncio.run(oi_scheduler._try_final_retry("VIX", today))

    assert calls == ["VIX"]
    assert "VIX" not in oi_scheduler._last_success_date
    assert oi_scheduler._final_retry_done["VIX"] == today


def test_try_final_retry_resets_cooldown_before_forcing(monkeypatch):
    # El intento final debe saltear el cooldown de fallos de
    # marketdata_client (a diferencia del force=True normal, que sí lo
    # respeta) -- confirma que se resetea _last_attempt antes de llamar.
    from app.integrations import marketdata_client

    oi_scheduler._last_success_date.clear()
    oi_scheduler._final_retry_done.clear()
    marketdata_client._last_attempt["VIX"] = 999999999999.0  # "acaba de fallar"
    _install_fake_fetch(monkeypatch, {"VIX": [{(15.0, "call"): 1}]})

    today = datetime(2026, 9, 11).date()
    asyncio.run(oi_scheduler._try_final_retry("VIX", today))

    assert marketdata_client._last_attempt["VIX"] == 0.0
