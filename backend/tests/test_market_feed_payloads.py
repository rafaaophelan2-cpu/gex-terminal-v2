import pandas as pd

from app.services.market_feed import SymbolFeed


def _feed_with(df: pd.DataFrame, spot: float) -> SymbolFeed:
    feed = SymbolFeed("QQQ", strikes_count=25)
    feed.df = df
    feed.spot_price = spot
    return feed


def _chain_with_flip_at(flip_strike: float, lo: int, hi: int) -> pd.DataFrame:
    rows = []
    for strike in range(lo, hi + 1):
        net_gex = 50.0 if strike <= flip_strike else -30.0
        rows.append({
            "strike": float(strike), "exp_key": "e0", "dte": 0,
            "net_gex": net_gex,
            "call_gex": net_gex if net_gex > 0 else 0.0,
            "put_gex": net_gex if net_gex < 0 else 0.0,
            # El flip sale del open interest (perfil de precio): más calls
            # que puts hasta flip_strike y al revés por encima, con el
            # mismo neto a cada lado -> el gamma total cruza cero a mitad
            # de camino entre flip_strike y el strike siguiente.
            "openInterest_c": 30 if strike <= flip_strike else 10,
            "openInterest_p": 10 if strike <= flip_strike else 30,
        })
    return pd.DataFrame(rows)


def test_gex_info_payload_flip_uses_ladder_not_the_on_screen_clipped_strike_range():
    # Bug real que esto corrige: antes, flip_level salía de 'by_strike',
    # recortado al [min_strike, max_strike] que el usuario eligió ver en
    # pantalla (strike_range del sidebar) -- acá el cruce real de signo
    # (entre 715 y 716) queda FUERA de la ventana visible 710-714. Con la
    # ladder (±15 strikes reales, nunca recortada por lo que alguien esté
    # mirando en pantalla) el flip real sigue apareciendo.
    df = _chain_with_flip_at(flip_strike=715, lo=700, hi=730)
    feed = _feed_with(df, spot=712.0)

    payload = feed.gex_info_payload(min_strike=710.0, max_strike=714.0)

    assert abs(payload["flip_level"] - 715.5) < 0.25  # cruce real, casi a mitad de 715 y 716
    assert payload["flip_level"] > 714.0  # fuera de la ventana visible, no pegado a su borde
    # El bar chart (by_strike) sigue recortado a la ventana on-screen -- el
    # fix es solo para el flip, no cambia el resto del panel.
    assert {r["strike"] for r in payload["by_strike"]} == {710.0, 711.0, 712.0, 713.0, 714.0}


def test_gex_info_payload_includes_oi_ladder_and_defaults_to_0dte():
    df = _chain_with_flip_at(flip_strike=505, lo=490, hi=510)
    feed = _feed_with(df, spot=500.0)

    payload = feed.gex_info_payload()

    assert payload["oi_ladder"]
    assert {row["strike"] for row in payload["oi_ladder"]} == set(float(s) for s in range(490, 511))


def test_gex_info_payload_expiration_filter_selects_next_expiration_ladder():
    df = pd.concat([
        _chain_with_flip_at(flip_strike=505, lo=490, hi=510),
        pd.DataFrame([
            {"strike": 500.0, "exp_key": "e7", "dte": 7, "net_gex": 1.0, "call_gex": 1.0, "put_gex": 0.0,
             "openInterest_c": 10, "openInterest_p": 10},
        ]),
    ], ignore_index=True)
    feed = _feed_with(df, spot=500.0)

    payload = feed.gex_info_payload(expiration="next")

    assert {row["strike"] for row in payload["oi_ladder"]} == {500.0}
    # El resto del panel (bar chart de siempre) sigue fijo a 0DTE, sin
    # cambio de comportamiento por el filtro nuevo.
    assert 500.0 in {r["strike"] for r in payload["by_strike"]}
    assert len(payload["by_strike"]) == 21  # 490..510, la expiración 0DTE de siempre


def test_gex_info_payload_empty_feed_returns_empty_ladder():
    feed = SymbolFeed("QQQ", strikes_count=25)
    payload = feed.gex_info_payload()
    assert payload["oi_ladder"] == []
    # Sin cadena no hay flip ni walls reales: None (la web muestra '--'),
    # no el spot.
    assert payload["flip_level"] is None
    assert set(payload["walls"].values()) == {None}


def test_walls_and_totals_come_from_the_full_chain_not_the_on_screen_window():
    # Auditoría 26-sep-2026: los walls salían del by_strike recortado al
    # Strike Range de la conexión (mismo bug que tenía el flip). Con una
    # ventana 710-714, el CW1 real (720, el mayor net_gex positivo) quedaba
    # fuera y el panel mostraba el mayor positivo DE LA VENTANA.
    rows = []
    for strike in range(700, 731):
        net = 5.0
        if strike == 720:
            net = 900.0
        if strike == 712:
            net = 50.0
        if strike == 703:
            net = -700.0
        rows.append({
            "strike": float(strike), "exp_key": "e0", "dte": 0, "net_gex": net,
            "call_gex": max(net, 0.0), "put_gex": min(net, 0.0),
            "openInterest_c": 10, "openInterest_p": 10,
        })
    feed = _feed_with(pd.DataFrame(rows), spot=712.0)

    windowed = feed.gex_info_payload(min_strike=710.0, max_strike=714.0)
    full = feed.gex_info_payload()

    assert windowed["walls"]["cw1"] == 720.0
    assert windowed["walls"]["pw1"] == 703.0
    assert windowed["walls"] == full["walls"]
    # Los totales tampoco dependen del zoom.
    assert windowed["net_gex_total"] == full["net_gex_total"]
    # El gráfico de barras sí sigue recortado.
    assert {r["strike"] for r in windowed["by_strike"]} == {710.0, 711.0, 712.0, 713.0, 714.0}


def test_fast_chain_fetch_asks_for_enough_strikes_for_the_15_strike_ladder():
    # Auditoría #7: con Strike Range 25 Schwab devolvía 25 strikes en total
    # y la ladder "±15" salía con ±12.
    assert SymbolFeed("QQQ", strikes_count=25).fetch_strikes_count == 31
    assert SymbolFeed("QQQ", strikes_count=60).fetch_strikes_count == 60


def test_greeks_totals_do_not_depend_on_the_on_screen_window():
    rows = []
    for strike in range(700, 721):
        rows.append({
            "strike": float(strike), "exp_key": "e0", "dte": 0,
            "net_dex": 1.0, "net_tex": 1.0, "net_vex": 1.0, "net_chex": 1.0, "net_vanna": 1.0,
            "call_dex": 1.0, "put_dex": 0.0,
        })
    feed = _feed_with(pd.DataFrame(rows), spot=710.0)

    windowed = feed.greeks_payload(min_strike=708.0, max_strike=712.0)

    assert windowed["totals"]["dex"] == 21.0
    assert len(windowed["by_strike"]) == 5
