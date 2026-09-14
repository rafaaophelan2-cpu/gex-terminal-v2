import asyncio

import pytest

from app.services.market_feed import FeedRegistry


@pytest.fixture(autouse=True)
def _no_real_background_tasks(monkeypatch):
    # start()/stop() normalmente crean asyncio.Task-s que corren
    # _run_loop/_deep_run_loop de verdad (llamadas reales a Schwab) --
    # para testear solo la lógica de ref-count/ensanchado de
    # FeedRegistry.subscribe(), se los reemplaza por no-ops.
    from app.services.market_feed import SymbolFeed

    monkeypatch.setattr(SymbolFeed, "start", lambda self: None)
    monkeypatch.setattr(SymbolFeed, "stop", lambda self: None)


def test_subscribe_creates_feed_with_requested_strikes_count():
    registry = FeedRegistry()
    feed = asyncio.run(registry.subscribe("QQQ", strikes_count=25))
    assert feed.strikes_count == 25


def test_subscribe_widens_shared_feed_for_a_second_subscriber_with_a_wider_range():
    # Bug real: el feed de un símbolo es COMPARTIDO (ref-count, un solo
    # fetch a Schwab) -- 'strikes_count' antes solo se aplicaba al CREAR
    # el feed. Un segundo usuario pidiendo un rango más ancho para el
    # MISMO símbolo quedaba silenciosamente recortado al rango del
    # primero, sin ningún error.
    registry = FeedRegistry()
    feed_a = asyncio.run(registry.subscribe("QQQ", strikes_count=25))
    feed_b = asyncio.run(registry.subscribe("QQQ", strikes_count=60))

    assert feed_a is feed_b  # mismo feed compartido
    assert feed_a.strikes_count == 60  # ensanchado al máximo pedido


def test_subscribe_does_not_shrink_shared_feed_for_a_narrower_request():
    registry = FeedRegistry()
    asyncio.run(registry.subscribe("QQQ", strikes_count=60))
    feed = asyncio.run(registry.subscribe("QQQ", strikes_count=25))

    # No se achica solo -- un rango más angosto pedido después no debe
    # recortar los datos que el primer suscriptor (todavía activo) pidió.
    assert feed.strikes_count == 60
