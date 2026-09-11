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

    def execute(self):
        return SimpleNamespace(data=self.existing_rows)


class _FakeTable:
    def __init__(self, existing_rows):
        self.existing_rows = existing_rows
        self.inserted = []
        self.last_query = None

    def select(self, *_args):
        self.last_query = _FakeQuery(self.existing_rows)
        return self.last_query

    def insert(self, payload):
        self.inserted.append(payload)
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[payload]))


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
