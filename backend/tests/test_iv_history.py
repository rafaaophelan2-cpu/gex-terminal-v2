import asyncio
from datetime import datetime, timedelta, timezone

import app.integrations.supabase_client as supabase_client
from tests.fake_postgrest import FakePostgrestClient


def _minute_rows(days: int, per_day: int = 390, symbol: str = "QQQ") -> list[dict]:
    """Un snapshot por minuto de sesión (13:30-20:00 UTC en horario de
    verano de NY), 'days' días hábiles hacia atrás desde el 25-sep-2026.
    La IV de cada día es 0.10 + 0.01 * índice, y la última fila del día
    (el cierre) es la que manda."""
    rows = []
    day = datetime(2026, 9, 25, tzinfo=timezone.utc)
    made = 0
    while made < days:
        if day.weekday() < 5:
            start = day.replace(hour=13, minute=30)
            for m in range(per_day):
                ts = start + timedelta(minutes=m)
                rows.append({
                    "symbol": symbol,
                    "created_at": ts.isoformat(),
                    "time": (ts - timedelta(hours=4)).strftime("%H:%M"),
                    "atm_iv": 0.10 + 0.01 * made,
                })
            made += 1
        day -= timedelta(days=1)
    return rows


def _setup(monkeypatch, rows):
    supabase_client._daily_iv_cache.clear()
    supabase_client._available_dates_cache.clear()
    client = FakePostgrestClient(rows)
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: client)
    return client


def test_iv_history_sees_every_day_despite_the_1000_row_cap(monkeypatch):
    # Bug real (#9): .limit(5000) devolvía 1,000 filas = ~2.5 sesiones, así
    # que el percentil real nunca juntaba los 10 días y la web seguía con
    # la fórmula estimada.
    _setup(monkeypatch, _minute_rows(days=15))

    history = asyncio.run(supabase_client.fetch_daily_atm_iv_history("QQQ"))

    assert len(history) == 15
    # Más reciente primero; un valor por día.
    assert [round(v, 2) for v in history[:3]] == [0.10, 0.11, 0.12]


def test_iv_history_caches_closed_days_and_only_walks_new_ones(monkeypatch):
    client = _setup(monkeypatch, _minute_rows(days=12))
    asyncio.run(supabase_client.fetch_daily_atm_iv_history("QQQ"))
    first_calls = client.calls
    assert first_calls >= 12

    history = asyncio.run(supabase_client.fetch_daily_atm_iv_history("QQQ"))

    assert len(history) == 12
    # Segunda vuelta: el último día (no es "hoy") ya está en caché -> 1 consulta.
    assert client.calls - first_calls <= 2


def test_iv_history_ignores_other_symbols_and_null_iv(monkeypatch):
    rows = _minute_rows(days=3) + _minute_rows(days=5, symbol="SPY")
    rows.append({"symbol": "QQQ", "created_at": "2026-09-28T15:00:00+00:00", "time": "11:00", "atm_iv": None})
    _setup(monkeypatch, rows)

    assert len(asyncio.run(supabase_client.fetch_daily_atm_iv_history("QQQ"))) == 3


def test_available_dates_sees_every_session_despite_the_cap(monkeypatch):
    from zoneinfo import ZoneInfo

    _setup(monkeypatch, _minute_rows(days=8))

    dates = asyncio.run(supabase_client.fetch_available_dates("QQQ", ZoneInfo("America/New_York")))

    assert len(dates) == 8
    assert dates[0] == "2026-09-25"
    assert dates == sorted(dates, reverse=True)


def test_parse_ts_tolerates_short_fractions_and_z():
    a = supabase_client._parse_ts("2026-09-26T19:59:12.12345+00:00")
    b = supabase_client._parse_ts("2026-09-26T19:59:12Z")
    assert a.tzinfo is not None and b.tzinfo is not None
    assert a.microsecond == 123450
