"""Cliente falso de supabase-py que SÍ filtra, ordena y respeta el tope
"Max rows" de PostgREST (1,000 por defecto): devuelve como mucho eso
aunque se pida más, sin error, igual que el real. Sirve para probar
consultas que antes pasaban los tests con fakes que ignoraban los filtros
y fallaban en producción por el tope."""
from types import SimpleNamespace

MAX_ROWS = 1000


class _Not:
    def __init__(self, query):
        self._q = query

    def is_(self, col, value):
        assert value == "null"
        self._q._preds.append(lambda r: r.get(col) is not None)
        return self._q


class _Query:
    def __init__(self, client, rows):
        self._client = client
        self._rows = rows
        self._preds = []
        self._order = None
        self._limit = None

    @property
    def not_(self):
        return _Not(self)

    def eq(self, col, v):
        self._preds.append(lambda r: r.get(col) == v)
        return self

    def gte(self, col, v):
        self._preds.append(lambda r: r.get(col) is not None and r.get(col) >= v)
        return self

    def lte(self, col, v):
        self._preds.append(lambda r: r.get(col) is not None and r.get(col) <= v)
        return self

    def lt(self, col, v):
        # created_at se compara como instante, no como texto.
        if col == "created_at":
            from app.integrations.supabase_client import _parse_ts
            ref = _parse_ts(v)
            self._preds.append(lambda r: _parse_ts(r[col]) < ref)
        else:
            self._preds.append(lambda r: r.get(col) is not None and r.get(col) < v)
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        self._client.calls += 1
        out = [r for r in self._rows if all(p(r) for p in self._preds)]
        if self._order:
            col, desc = self._order
            out.sort(key=lambda r: r[col], reverse=desc)
        n = min(self._limit or MAX_ROWS, MAX_ROWS)
        return SimpleNamespace(data=out[:n])


class _Table:
    def __init__(self, client, rows):
        self._client = client
        self._rows = rows

    def select(self, *_args, **_kwargs):
        return _Query(self._client, self._rows)


class FakePostgrestClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def table(self, _name):
        return _Table(self, self.rows)
