import asyncio
from types import SimpleNamespace

import app.integrations.supabase_client as supabase_client


class _FakeQuery:
    def __init__(self, existing_rows):
        self.existing_rows = existing_rows
        self.filters = []

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def gte(self, col, val):
        self.filters.append(("gte", col, val))
        return self

    def lt(self, col, val):
        self.filters.append(("lt", col, val))
        return self

    def limit(self, n):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=self.existing_rows)


class _FakeDelete:
    def __init__(self, table):
        self.table = table
        self.filters = []

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def execute(self):
        self.table.deleted_filters = self.filters
        return SimpleNamespace(data=[])


class _FakeTable:
    def __init__(self, existing_rows):
        self.existing_rows = existing_rows
        self.inserted = []
        self.last_query = None
        self.deleted_filters = None

    def select(self, *_args):
        self.last_query = _FakeQuery(self.existing_rows)
        return self.last_query

    def insert(self, payload):
        self.inserted.append(payload)
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[payload]))

    def delete(self):
        return _FakeDelete(self)


class _FakeClient:
    def __init__(self, existing_rows):
        self._table = _FakeTable(existing_rows)

    def table(self, _name):
        return self._table


SNAPSHOT = {"symbol": "QQQ", "time": "09:30", "spot": 500.0, "net_gex": 1.0, "strikes": []}


def test_insert_gex_snapshot_inserts_when_no_row_for_today(monkeypatch):
    fake_client = _FakeClient(existing_rows=[])
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: fake_client)

    asyncio.run(supabase_client.insert_gex_snapshot(SNAPSHOT))

    assert len(fake_client._table.inserted) == 1


def test_insert_gex_snapshot_skips_when_row_already_exists_today(monkeypatch):
    fake_client = _FakeClient(existing_rows=[{"id": 1}])
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: fake_client)

    asyncio.run(supabase_client.insert_gex_snapshot(SNAPSHOT))

    assert len(fake_client._table.inserted) == 0


def test_insert_gex_snapshot_scopes_dedup_check_to_today_not_all_time(monkeypatch):
    # Bug real: comparar solo symbol+time hacía que el "09:30" de hoy
    # calzara con el "09:30" de CUALQUIER día anterior y nunca se
    # insertara nada nuevo -- el chequeo de existencia debe acotarse al
    # día en curso con created_at (gte/lt), no solo symbol+time.
    fake_client = _FakeClient(existing_rows=[])
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: fake_client)

    asyncio.run(supabase_client.insert_gex_snapshot(SNAPSHOT))

    filters = fake_client._table.last_query.filters
    filter_cols = {f[1] for f in filters}
    assert "created_at" in filter_cols
    ops_on_created_at = {f[0] for f in filters if f[1] == "created_at"}
    assert ops_on_created_at == {"gte", "lt"}


def test_fetch_available_dates_excludes_weekend_rows(monkeypatch):
    # Bug real visto en producción un domingo: Schwab sigue sirviendo la
    # última chain conocida (de un viernes) 24/7, y el filtro de horario
    # (09:30-16:00 NY) por sí solo no distingue el día -- una fila de
    # domingo dentro de ese rango horario "ganaba" como fecha más
    # reciente, dejando LIVE GAMMA con una sesión de minutos en vez de la
    # última sesión real. 2026-09-13 es domingo, 2026-09-11 es viernes.
    from zoneinfo import ZoneInfo

    fake_client = _FakeClient(existing_rows=[
        {"created_at": "2026-09-13T16:30:00+00:00", "time": "12:30"},  # domingo, en horario
        {"created_at": "2026-09-11T17:30:00+00:00", "time": "13:30"},  # viernes, en horario
    ])
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: fake_client)

    dates = asyncio.run(supabase_client.fetch_available_dates("QQQ", ZoneInfo("America/New_York")))

    assert "2026-09-13" not in dates
    assert "2026-09-11" in dates


def test_fetch_chat_history_scopes_by_username(monkeypatch):
    fake_client = _FakeClient(existing_rows=[
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "hola, en qué te ayudo?"},
    ])
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: fake_client)

    rows = asyncio.run(supabase_client.fetch_chat_history("trader1"))

    assert len(rows) == 2
    filters = fake_client._table.last_query.filters
    assert ("eq", "user_email", "trader1") in filters


def test_insert_chat_message_tags_with_username(monkeypatch):
    fake_client = _FakeClient(existing_rows=[])
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: fake_client)

    asyncio.run(supabase_client.insert_chat_message("trader1", "user", "hola"))

    assert fake_client._table.inserted == [
        {"role": "user", "content": "hola", "user_email": "trader1"}
    ]


def test_clear_chat_history_only_deletes_current_user(monkeypatch):
    fake_client = _FakeClient(existing_rows=[])
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: fake_client)

    asyncio.run(supabase_client.clear_chat_history("trader1"))

    assert fake_client._table.deleted_filters == [("eq", "user_email", "trader1")]
