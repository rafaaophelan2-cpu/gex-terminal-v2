import asyncio

import pandas as pd

from app.services import ai_context


class _FakeFeed:
    def __init__(self):
        self.spot_price = 481.23
        self.nearest_exp_key = "2026-09-11:0"
        self.oi_is_volume_proxy = False
        self.macro_levels = {}
        self.df = pd.DataFrame([
            {"strike": 475.0, "exp_key": "2026-09-11:0", "dte": 0, "net_gex": -5.0, "call_gex": 1.0, "put_gex": -6.0,
             "net_dex": 1.0, "net_tex": -1.0, "net_vex": 1.0, "net_chex": -1.0, "net_vanna": 1.0},
            {"strike": 485.0, "exp_key": "2026-09-11:0", "dte": 0, "net_gex": 3.0, "call_gex": 4.0, "put_gex": -1.0,
             "net_dex": 1.0, "net_tex": -1.0, "net_vex": 1.0, "net_chex": -1.0, "net_vanna": 1.0},
        ])


def test_build_ai_context_uses_the_spot_captured_at_the_start_even_if_the_feed_ticks_mid_gather(monkeypatch):
    # Bug real: 'metrics' (walls/zero-gamma) se calculaba desde
    # feed.spot_price ANTES del asyncio.gather() de más abajo (que puede
    # tardar varios segundos, llamadas a Schwab serializadas detrás de un
    # lock único) -- pero 'intraday_context'/'implied_range'/el "spot"
    # final del dict volvían a leer feed.spot_price DESPUÉS de que el
    # gather terminara, momento en el que el tick de fondo del mismo feed
    # (corre cada ~2s) puede haberlo movido. Se simula acá mutando
    # feed.spot_price DURANTE una de las llamadas del gather, como haría
    # el tick loop real corriendo en paralelo.
    feed = _FakeFeed()
    original_spot = feed.spot_price

    async def _fake_fetch_price_history(symbol, day):
        feed.spot_price = 999.99  # el "tick de fondo" mueve el spot a mitad del gather
        return []

    async def _fake_fetch_vix():
        return 18.5

    async def _fake_fetch_session_profile(key):
        return None

    async def _fake_fetch_vix_term_structure():
        return {}

    async def _fake_fetch_ndx_compounded_levels(symbol, spot, metrics):
        # Debe recibir el spot ORIGINAL (capturado antes del gather), no
        # el mutado a mitad de camino.
        assert spot == original_spot
        return None

    async def _fake_fetch_vix_gamma_levels(symbol):
        return None

    async def _fake_fetch_economic_calendar():
        return []

    monkeypatch.setattr(ai_context.feed_registry, "get", lambda symbol: feed)
    monkeypatch.setattr(ai_context, "fetch_price_history", _fake_fetch_price_history)
    monkeypatch.setattr(ai_context, "fetch_vix", _fake_fetch_vix)
    monkeypatch.setattr(ai_context, "fetch_session_profile", _fake_fetch_session_profile)
    monkeypatch.setattr(ai_context, "fetch_vix_term_structure", _fake_fetch_vix_term_structure)
    monkeypatch.setattr(ai_context, "fetch_ndx_compounded_levels", _fake_fetch_ndx_compounded_levels)
    monkeypatch.setattr(ai_context, "fetch_vix_gamma_levels", _fake_fetch_vix_gamma_levels)
    monkeypatch.setattr(ai_context, "fetch_economic_calendar", _fake_fetch_economic_calendar)

    ctx = asyncio.run(ai_context.build_ai_context("QQQ"))

    # feed.spot_price ya quedó en 999.99 (el tick de fondo lo movió), pero
    # el contexto entero (spot declarado + todo lo derivado de él) debe
    # ser internamente consistente con el spot de ANTES del gather.
    assert feed.spot_price == 999.99
    assert ctx["spot"] == original_spot
