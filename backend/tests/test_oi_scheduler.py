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
