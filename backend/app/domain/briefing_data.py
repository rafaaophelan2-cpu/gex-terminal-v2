from datetime import datetime

import pandas as pd

from app.domain.gex_math import compute_zero_gamma
from app.domain.implied_range import compute_implied_range
from app.domain.metrics import compute_metrics_for_dte
from app.domain.oi_ladder import build_oi_ladder, compute_atm_straddle, compute_flip_from_ladder, resolve_expiration_key
from app.domain.quantower import build_eod_levels_from_snapshot

# 09:30-16:00 NY (mismo criterio que DEFAULT_SESSION_START/END en
# domain/drift.py) define "open"; antes de eso en día hábil es
# "premarket"; cualquier otra cosa (después del cierre, o fin de semana)
# es "closed". No hace falta más precisión que esta -- lo único que
# Claude (chat) necesita del estado de mercado es si los datos que sigue
# son en vivo o del último cierre conocido (ver 'data_as_of').
_SESSION_START = "09:30"
_SESSION_END = "16:00"


def compute_market_status(now_ny: datetime) -> str:
    """'premarket'|'open'|'closed' a partir de la hora de NY -- 'now_ny'
    debe venir YA convertido a America/New_York (mismo criterio que
    snapshot_writer.py/drift.py, que también comparan 'HH:MM' como
    string, más barato que comparar objetos time)."""
    if now_ny.weekday() >= 5:  # sábado=5, domingo=6
        return "closed"
    time_str = now_ny.strftime("%H:%M")
    if time_str < _SESSION_START:
        return "premarket"
    if time_str <= _SESSION_END:
        return "open"
    return "closed"


def filter_calendar_today(calendar: list[dict] | None, today_str: str) -> list[dict]:
    """Recorta fetch_economic_calendar() (que trae la SEMANA relevante,
    ver forexfactory_client.py) a solo 'today_str' (ISO, ej.
    "2026-09-17") y a impacto medio/alto -- el nodo público está pensado
    para que Claude vea de un vistazo qué puede mover el mercado HOY, no
    toda la semana (eso ya lo tiene el endpoint /market/economic-calendar
    para la pestaña News). Agrega 'released' (True si 'actual' ya vino
    con un valor, o sea el dato ya salió) para que Claude no tenga que
    inferirlo de si 'actual' es None."""
    if not calendar:
        return []
    return [
        {**ev, "released": ev.get("actual") not in (None, "")}
        for ev in calendar
        if ev.get("date") == today_str and ev.get("impact") in ("medium", "high")
    ]


# Explicación de unidades por métrica -- derivadas directo de las fórmulas
# reales en domain/gex_math.py (compute_greeks_exposures/
# recalculate_gex_for_spot), para que Claude no tenga que adivinar ni
# asumir una convención distinta a la que este backend realmente usa.
UNITS = {
    "net_gex": "USD de gamma exposure por cada 1% de movimiento del subyacente (gamma * OI * spot^2 * 0.01)",
    "dex": "millones de USD de exposición direccional equivalente (delta * OI * 100 * spot / 1e6)",
    "tex": "USD de decaimiento de prima por día (theta * OI * 100)",
    "vex": "USD de cambio de prima por cada 1 punto de IV (vega * OI * 100)",
    "chex": "millones de USD de delta que se gana/pierde por día solo por paso del tiempo (charm * OI * 100 * spot / 1e6)",
    "vanna": "millones de USD de delta que cambia por cada 1 punto de cambio en IV (vanna * OI * 100 * spot / 1e6)",
    "oi": "contratos de open interest (1 contrato = 100 acciones/unidades subyacentes)",
    "volume": "contratos operados en el día",
    "straddle": "USD de prima real de mercado (mark = aproximación al precio medio bid/ask de Schwab), no por contrato x100",
    "expected_move": "USD de movimiento esperado (1 desviación estándar) hasta el cierre de la expiración 0DTE",
}


def _empty_totals() -> dict:
    return {"net_gex": None, "dex": None, "tex": None, "vex": None, "chex": None, "vanna": None}


def _totals_from_metrics(metrics: dict) -> dict:
    return {
        "net_gex": metrics.get("net_gex_total"),
        "dex": metrics.get("net_dex_val"),
        "tex": metrics.get("net_tex_val"),
        "vex": metrics.get("net_vex_val"),
        "chex": metrics.get("net_chex_val"),
        "vanna": metrics.get("net_vanna_val"),
    }


def _public_ladder(internal_ladder: list[dict]) -> list[dict]:
    """Traduce la ladder interna (domain/oi_ladder.py, nombres como
    'net_gex'/'net_vanna'/'net_chex' para no chocar con call_gex/put_gex)
    al shape público y estable que consume /briefing_data -- gex/vanna/
    charm a secas, sin desglose call/put (no pedido acá)."""
    return [
        {
            "strike": row["strike"],
            "call_oi": row["call_oi"],
            "put_oi": row["put_oi"],
            "call_volume": row["call_volume"],
            "put_volume": row["put_volume"],
            "gex": row["net_gex"],
            "vanna": row["net_vanna"],
            "charm": row["net_chex"],
        }
        for row in internal_ladder
    ]


def _build_meta(
    symbol: str, spot: float, timestamp_utc: str, market_status: str, data_as_of: str,
    expiration_0dte: str | None, expiration_next: str | None,
) -> dict:
    return {
        "symbol": symbol,
        "spot": spot,
        "timestamp_utc": timestamp_utc,
        "market_status": market_status,
        "data_as_of": data_as_of,
        "expiration_0dte": expiration_0dte,
        "expiration_next": expiration_next,
        "units": UNITS,
    }


def build_briefing_payload_live(
    symbol: str,
    df: pd.DataFrame,
    spot_price: float,
    atm_iv: float,
    dte_0dte: float,
    market_status: str,
    timestamp_utc: str,
    data_as_of: str,
    vix_term_structure: dict | None,
    calendar_today: list[dict],
    opening_net_gex: float | None,
) -> dict:
    """Payload completo de /briefing_data/{symbol} a partir de un
    SymbolFeed activo -- reusa TAL CUAL los mismos cálculos que ya
    alimentan el dashboard por WebSocket (compute_metrics_for_dte para
    los totales por Griega, domain/oi_ladder.py para la ladder/flip/
    straddle, domain/implied_range.py para el expected move): nada de
    esto se recalcula distinto acá, solo se empaqueta para Firebase.

    'timestamp_utc' es CUÁNDO se arma este payload (ahora); 'data_as_of'
    es de CUÁNDO son los datos reales (el último tick de Schwab, ver
    SymbolFeed.last_update) -- un feed técnicamente "activo" pero
    congelado fuera de horario (Schwab sirve la última chain conocida
    indefinidamente, ver schwab_client.py::call_with_fallback) debe
    seguir mostrando la hora real del último dato, no la hora actual."""
    exp_0dte = resolve_expiration_key(df, "0dte")
    # resolve_expiration_key('next') cae al mismo exp_key que '0dte' si
    # 'df' solo tiene una expiración cargada (ver oi_ladder.py) -- en ese
    # caso no hay una 'próxima' real que mostrar, así que totals_next/
    # ladder_next/flip_next quedan explícitamente vacíos en vez de
    # duplicar los mismos números de 0DTE bajo un nombre distinto.
    exp_next_raw = resolve_expiration_key(df, "next")
    has_next = exp_next_raw is not None and exp_next_raw != exp_0dte
    exp_next = exp_next_raw if has_next else None

    totals_0dte = _totals_from_metrics(compute_metrics_for_dte(df, [exp_0dte] if exp_0dte else [], spot_price))
    totals_next = _totals_from_metrics(compute_metrics_for_dte(df, [exp_next], spot_price)) if has_next else _empty_totals()

    ladder_0dte = build_oi_ladder(df, spot_price, expiration="0dte")
    ladder_next = build_oi_ladder(df, spot_price, expiration="next") if has_next else []

    flip_0dte = compute_flip_from_ladder(ladder_0dte, spot_price)
    flip_next = compute_flip_from_ladder(ladder_next, spot_price) if has_next else None

    straddle_atm_0dte = compute_atm_straddle(df, spot_price, expiration="0dte")
    implied_range = compute_implied_range(spot_price, atm_iv, dte_0dte)

    gex_change_since_open = (
        totals_0dte["net_gex"] - opening_net_gex
        if totals_0dte["net_gex"] is not None and opening_net_gex is not None
        else None
    )

    return {
        "meta": _build_meta(symbol, spot_price, timestamp_utc, market_status, data_as_of, exp_0dte, exp_next),
        "totals_0dte": totals_0dte,
        "totals_next": totals_next,
        "ladder_0dte": _public_ladder(ladder_0dte),
        "ladder_next": _public_ladder(ladder_next),
        "flip_0dte": flip_0dte,
        "flip_next": flip_next,
        "straddle_atm_0dte": straddle_atm_0dte,
        "expected_move": implied_range.get("expected_move"),
        "implied_range": implied_range,
        "net_gex_change_since_open": gex_change_since_open,
        "vix": {
            "vix": (vix_term_structure or {}).get("vix"),
            "vix3m": (vix_term_structure or {}).get("vix3m"),
            "term_structure": (vix_term_structure or {}).get("state"),
        },
        "calendar_today": calendar_today,
    }


def build_briefing_payload_from_snapshot(
    symbol: str,
    snapshot: dict,
    market_status: str,
    timestamp_utc: str,
    vix_term_structure: dict | None,
    calendar_today: list[dict],
    opening_net_gex: float | None,
) -> dict | None:
    """Fallback para cuando NO hay ningún SymbolFeed activo (nadie tiene
    el dashboard abierto -- fuera de horario, o el proceso recién
    arrancó): reconstruye lo que se pueda del último snapshot guardado en
    Supabase (mismo criterio que GET /market/premarket-briefing, ver
    domain/quantower.py::build_eod_levels_from_snapshot). Los snapshots
    NUNCA guardaron Open Interest real, Griegas (DEX/TEX/VEX/Vanna) ni
    precios mark -- esos campos vienen None/[] acá en vez de inventados;
    solo net_gex, Charm (si ese snapshot lo tenía) y el flip (zero_gamma)
    son reconstruibles de verdad."""
    eod = build_eod_levels_from_snapshot(snapshot)
    if eod is None:
        return None

    strikes = snapshot.get("strikes") or []
    has_chex = any("net_chex" in s for s in strikes)
    chex_total = sum(float(s.get("net_chex", 0.0)) for s in strikes) if has_chex else None

    totals_0dte = _empty_totals()
    totals_0dte["net_gex"] = float(snapshot.get("net_gex", 0.0) or 0.0)
    totals_0dte["chex"] = chex_total

    gex_change_since_open = (
        totals_0dte["net_gex"] - opening_net_gex
        if opening_net_gex is not None
        else None
    )

    return {
        "meta": _build_meta(
            symbol, eod["spot"], timestamp_utc, market_status,
            data_as_of=snapshot.get("created_at") or timestamp_utc,
            expiration_0dte=None, expiration_next=None,
        ),
        "totals_0dte": totals_0dte,
        "totals_next": _empty_totals(),
        "ladder_0dte": [],
        "ladder_next": [],
        "flip_0dte": eod["zero_gamma"],
        "flip_next": None,
        "straddle_atm_0dte": None,
        "expected_move": None,
        "implied_range": None,
        "net_gex_change_since_open": gex_change_since_open,
        "vix": {
            "vix": (vix_term_structure or {}).get("vix"),
            "vix3m": (vix_term_structure or {}).get("vix3m"),
            "term_structure": (vix_term_structure or {}).get("state"),
        },
        "calendar_today": calendar_today,
    }
