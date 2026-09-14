import asyncio
from datetime import datetime, tzinfo

import pandas as pd

import app.services.snapshot_writer as snapshot_writer


class _FakeFeed:
    def __init__(self):
        self.schwab_online = True
        self.spot_price = 500.0
        self.symbol = "QQQ"
        self.atm_iv = 0.2
        self.df = pd.DataFrame([
            {"strike": 500.0, "exp_key": "2026-09-14:0", "dte": 0, "call_gex": 1.0, "put_gex": -1.0, "net_gex": 0.0},
        ])


class _FixedDatetime(datetime):
    _fixed: "datetime | None" = None

    @classmethod
    def now(cls, tz: tzinfo | None = None):
        return cls._fixed if tz is None else cls._fixed.astimezone(tz)


def _install_fixed_now(monkeypatch, fixed: datetime):
    _FixedDatetime._fixed = fixed
    monkeypatch.setattr(snapshot_writer, "datetime", _FixedDatetime)


def _install_fake_insert(monkeypatch) -> list:
    inserted: list = []

    async def _fake_insert(snap):
        inserted.append(snap)

    monkeypatch.setattr(snapshot_writer, "insert_gex_snapshot", _fake_insert)
    return inserted


def test_write_snapshot_skips_on_sunday_even_within_session_hours(monkeypatch):
    # 2026-09-13 es domingo -- confirmado en vivo: Schwab sigue sirviendo
    # la última chain conocida (de un viernes) 24/7, así que el reloj de
    # NY caía igual dentro de 09:30-16:00 y se guardaban snapshots de un
    # día sin mercado, rompiendo available-dates (ver test_supabase_client.py).
    _install_fixed_now(monkeypatch, datetime(2026, 9, 13, 12, 30, tzinfo=snapshot_writer.STORAGE_TZ))
    inserted = _install_fake_insert(monkeypatch)

    asyncio.run(snapshot_writer._write_snapshot_for_feed(_FakeFeed()))

    assert inserted == []


def test_write_snapshot_skips_on_saturday(monkeypatch):
    _install_fixed_now(monkeypatch, datetime(2026, 9, 12, 12, 30, tzinfo=snapshot_writer.STORAGE_TZ))
    inserted = _install_fake_insert(monkeypatch)

    asyncio.run(snapshot_writer._write_snapshot_for_feed(_FakeFeed()))

    assert inserted == []


def test_write_snapshot_proceeds_on_weekday_within_session(monkeypatch):
    # 2026-09-11 es viernes.
    _install_fixed_now(monkeypatch, datetime(2026, 9, 11, 12, 30, tzinfo=snapshot_writer.STORAGE_TZ))
    inserted = _install_fake_insert(monkeypatch)

    asyncio.run(snapshot_writer._write_snapshot_for_feed(_FakeFeed()))

    assert len(inserted) == 1
    assert inserted[0]["symbol"] == "QQQ"


class _FakeFeedWithVolumeAndMark(_FakeFeed):
    def __init__(self):
        super().__init__()
        self.df = pd.DataFrame([
            {
                "strike": 500.0, "exp_key": "2026-09-14:0", "dte": 0,
                "call_gex": 1.0, "put_gex": -1.0, "net_gex": 0.0,
                "volume_c": 1200, "volume_p": 450, "mark_c": 1.57, "mark_p": 2.34,
            },
        ])


def test_write_snapshot_includes_volume_and_mark_when_present(monkeypatch):
    _install_fixed_now(monkeypatch, datetime(2026, 9, 11, 12, 30, tzinfo=snapshot_writer.STORAGE_TZ))
    inserted = _install_fake_insert(monkeypatch)

    asyncio.run(snapshot_writer._write_snapshot_for_feed(_FakeFeedWithVolumeAndMark()))

    strike = inserted[0]["strikes"][0]
    assert strike["volume_c"] == 1200
    assert strike["volume_p"] == 450
    assert strike["mark_c"] == 1.57
    assert strike["mark_p"] == 2.34


def test_write_snapshot_omits_volume_and_mark_when_absent(monkeypatch):
    # _FakeFeed (sin volume_c/volume_p/mark_c/mark_p en su df) sigue
    # funcionando igual que antes -- el guard has_volume/has_mark no debe
    # reventar con un DataFrame que no trae esas columnas (chains viejas).
    _install_fixed_now(monkeypatch, datetime(2026, 9, 11, 12, 30, tzinfo=snapshot_writer.STORAGE_TZ))
    inserted = _install_fake_insert(monkeypatch)

    asyncio.run(snapshot_writer._write_snapshot_for_feed(_FakeFeed()))

    strike = inserted[0]["strikes"][0]
    assert "volume_c" not in strike
    assert "mark_c" not in strike

