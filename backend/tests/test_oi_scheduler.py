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


def _clear_all_state():
    oi_scheduler._morning_success_date.clear()
    oi_scheduler._morning_final_retry_done.clear()
    oi_scheduler._evening_success_date.clear()
    oi_scheduler._evening_final_retry_done.clear()


def test_try_window_calls_fetch_and_marks_success(monkeypatch):
    _clear_all_state()
    calls = _install_fake_fetch(monkeypatch, {"VIX": [{(15.0, "call"): 1}]})

    today = datetime(2026, 9, 11).date()
    ok = asyncio.run(oi_scheduler._try_window("VIX", today, oi_scheduler._morning_success_date))

    assert ok is True
    assert calls == ["VIX"]
    assert oi_scheduler._morning_success_date["VIX"] == today


def test_try_window_skips_if_already_succeeded_today(monkeypatch):
    _clear_all_state()
    today = datetime(2026, 9, 11).date()
    oi_scheduler._morning_success_date["VIX"] = today
    calls = _install_fake_fetch(monkeypatch, {"VIX": [{(15.0, "call"): 1}]})

    ok = asyncio.run(oi_scheduler._try_window("VIX", today, oi_scheduler._morning_success_date))

    assert ok is True
    assert calls == []  # no debe volver a llamar a fetch_oi_map -- ya se consiguió hoy.


def test_try_window_does_not_mark_success_on_failure(monkeypatch):
    _clear_all_state()
    calls = _install_fake_fetch(monkeypatch, {"VIX": [None]})

    today = datetime(2026, 9, 11).date()
    ok = asyncio.run(oi_scheduler._try_window("VIX", today, oi_scheduler._morning_success_date))

    assert ok is False
    assert calls == ["VIX"]
    assert "VIX" not in oi_scheduler._morning_success_date


def test_morning_and_evening_windows_track_success_independently(monkeypatch):
    # Pedido explícito: un éxito a la mañana NO debe bloquear el intento
    # de la noche -- son ventanas independientes (la noche vuelve a
    # preguntar "¿cambió algo?" aunque la mañana ya haya funcionado).
    _clear_all_state()
    today = datetime(2026, 9, 11).date()
    oi_scheduler._morning_success_date["VIX"] = today
    calls = _install_fake_fetch(monkeypatch, {"VIX": [{(15.0, "call"): 2}]})

    ok = asyncio.run(oi_scheduler._try_window("VIX", today, oi_scheduler._evening_success_date))

    assert ok is True
    assert calls == ["VIX"]  # sí llamó -- la ventana nocturna es independiente de la de la mañana.
    assert oi_scheduler._evening_success_date["VIX"] == today


def test_try_final_retry_calls_fetch_when_window_failed(monkeypatch):
    _clear_all_state()
    calls = _install_fake_fetch(monkeypatch, {"VIX": [{(15.0, "call"): 1}]})

    today = datetime(2026, 9, 11).date()
    asyncio.run(oi_scheduler._try_final_retry(
        "VIX", today, oi_scheduler._morning_success_date, oi_scheduler._morning_final_retry_done, "pre-apertura",
    ))

    assert calls == ["VIX"]
    assert oi_scheduler._morning_success_date["VIX"] == today
    assert oi_scheduler._morning_final_retry_done["VIX"] == today


def test_try_final_retry_skips_if_window_already_succeeded(monkeypatch):
    _clear_all_state()
    today = datetime(2026, 9, 11).date()
    oi_scheduler._morning_success_date["VIX"] = today
    calls = _install_fake_fetch(monkeypatch, {"VIX": [{(15.0, "call"): 1}]})

    asyncio.run(oi_scheduler._try_final_retry(
        "VIX", today, oi_scheduler._morning_success_date, oi_scheduler._morning_final_retry_done, "pre-apertura",
    ))

    assert calls == []


def test_try_final_retry_only_fires_once_per_day_even_on_failure(monkeypatch):
    # Aunque el intento final también falle, no debe reintentarse en cada
    # chequeo del loop (cada 60s) dentro de la ventana final -- queda un
    # único intento por ventana por día.
    _clear_all_state()
    calls = _install_fake_fetch(monkeypatch, {"VIX": [None, {(15.0, "call"): 1}]})
    today = datetime(2026, 9, 11).date()

    asyncio.run(oi_scheduler._try_final_retry(
        "VIX", today, oi_scheduler._morning_success_date, oi_scheduler._morning_final_retry_done, "pre-apertura",
    ))
    asyncio.run(oi_scheduler._try_final_retry(
        "VIX", today, oi_scheduler._morning_success_date, oi_scheduler._morning_final_retry_done, "pre-apertura",
    ))

    assert calls == ["VIX"]
    assert "VIX" not in oi_scheduler._morning_success_date
    assert oi_scheduler._morning_final_retry_done["VIX"] == today


def test_evening_final_retry_independent_from_morning_final_retry(monkeypatch):
    _clear_all_state()
    today = datetime(2026, 9, 11).date()
    oi_scheduler._morning_final_retry_done["VIX"] = today
    calls = _install_fake_fetch(monkeypatch, {"VIX": [{(15.0, "call"): 1}]})

    asyncio.run(oi_scheduler._try_final_retry(
        "VIX", today, oi_scheduler._evening_success_date, oi_scheduler._evening_final_retry_done, "nocturno",
    ))

    assert calls == ["VIX"]  # el flag de "ya hecho" de la mañana no bloquea el de la noche.
    assert oi_scheduler._evening_success_date["VIX"] == today


def test_try_final_retry_resets_cooldown_before_forcing(monkeypatch):
    # El intento final debe saltear el cooldown de fallos de
    # marketdata_client (a diferencia del force=True normal, que sí lo
    # respeta) -- confirma que se resetea _last_attempt antes de llamar.
    from app.integrations import marketdata_client

    _clear_all_state()
    marketdata_client._last_attempt["VIX"] = 999999999999.0  # "acaba de fallar"
    _install_fake_fetch(monkeypatch, {"VIX": [{(15.0, "call"): 1}]})

    today = datetime(2026, 9, 11).date()
    asyncio.run(oi_scheduler._try_final_retry(
        "VIX", today, oi_scheduler._morning_success_date, oi_scheduler._morning_final_retry_done, "pre-apertura",
    ))

    assert marketdata_client._last_attempt["VIX"] == 0.0
