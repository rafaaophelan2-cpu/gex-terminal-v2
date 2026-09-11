import pandas as pd

# Ventana alrededor del spot donde se busca el strike "imán" (Magnet).
NEAR_SPOT_PCT = 0.03

# Referencias de magnitud "extrema" para normalizar cada factor del
# Gamma Squeeze Screener a 0-100% -- no son un estándar de la industria,
# son un punto de referencia razonable calibrado sobre el rango típico
# de QQQ/SPY que ya se ve en el resto de la app (paneles GEX INFO/GRID).
# Se documentan acá para poder ajustarlos si un símbolo con otra escala
# (ej. índices grandes) satura siempre el factor.
GAMMA_REGIME_REF = 20_000_000.0
DEX_REF = 500_000.0
CALL_WALL_PROXIMITY_PCT_REF = 5.0
VOLUME_OI_RATIO_REF = 0.5


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _pct_from_spot(level: float, spot: float) -> float:
    if spot <= 0:
        return 0.0
    return (level - spot) / spot * 100.0


def _classify_strength(magnitude: float, max_abs_gex: float) -> str:
    """STRONG/MODERATE relativo al strike más dominante del subset actual
    (no un umbral absoluto) -- así la clasificación tiene sentido tanto
    para un símbolo con GEX en millones como en cientos de millones."""
    if max_abs_gex <= 0:
        return "MODERATE"
    return "STRONG" if magnitude >= max_abs_gex * 0.5 else "MODERATE"


def _nearest_resistance_above(by_strike: pd.DataFrame, spot: float) -> pd.Series | None:
    """Strike positivo más cercano POR ENCIMA del spot -- el primer nivel
    donde el hedging de dealers cambia de forma relevante si se rompe.
    Usado tanto por la señal 'Resistance' como por el 'Trigger Level' del
    Gamma Squeeze Screener (son el mismo concepto: el próximo nivel real
    que hay que romper para que la tesis alcista tenga sentido)."""
    above = by_strike[(by_strike['strike'] > spot) & (by_strike['net_gex'] > 0)].sort_values('strike')
    if above.empty:
        return None
    return above.iloc[0]


def compute_signals(by_strike: pd.DataFrame, spot: float, walls: dict) -> list[dict]:
    """4 señales tipo 'tarjeta': lecturas directas de los niveles de gamma
    que la app ya calcula (paredes, gamma por strike), presentadas como
    'qué implica cada nivel clave' en vez de un gráfico. 'by_strike' debe
    traer una fila por strike con 'net_gex' ya sumado (mismo formato que
    gex_info_payload). No son un indicador nuevo -- son las mismas walls/
    zero-gamma de siempre, con una interpretación corta."""
    if by_strike is None or by_strike.empty or spot <= 0:
        return []

    max_abs_gex = float(by_strike['net_gex'].abs().max())
    net_gex_total = float(by_strike['net_gex'].sum())
    signals = []

    # 1. Régimen actual, al precio de spot: gamma neto positivo -> dealers
    # largos gamma -> compran caídas/venden subas -> amortiguan el
    # movimiento (bueno para vender volatilidad); negativo -> lo
    # contrario, amplifican el movimiento.
    if net_gex_total >= 0:
        signals.append({
            "type": "volatility_dampened", "title": "Volatility", "badge": _classify_strength(abs(net_gex_total), max_abs_gex),
            "description": "Movimientos de precio probablemente amortiguados -- bueno para vender volatilidad",
            "level": spot, "pct_from_spot": 0.0,
        })
    else:
        signals.append({
            "type": "volatility_increased", "title": "Volatility", "badge": _classify_strength(abs(net_gex_total), max_abs_gex),
            "description": "Se espera mayor volatilidad -- en este régimen los dealers amplifican el movimiento",
            "level": spot, "pct_from_spot": 0.0,
        })

    # 2. Magnet: el strike con mayor |net_gex| cerca del spot (+-3%) --
    # el hedging de dealers tiende a "clavar" el precio ahí, sobre todo
    # cerca de 0DTE.
    near = by_strike[
        (by_strike['strike'] >= spot * (1 - NEAR_SPOT_PCT)) & (by_strike['strike'] <= spot * (1 + NEAR_SPOT_PCT))
    ]
    if not near.empty:
        magnet = near.loc[near['net_gex'].abs().idxmax()]
        magnet_strike = float(magnet['strike'])
        signals.append({
            "type": "magnet", "title": "Magnet", "badge": _classify_strength(abs(float(magnet['net_gex'])), max_abs_gex),
            "description": "El precio tiende a gravitar hacia este nivel",
            "level": magnet_strike, "pct_from_spot": _pct_from_spot(magnet_strike, spot),
        })

    # 3. Resistance: próximo strike positivo por encima del spot.
    resistance = _nearest_resistance_above(by_strike, spot)
    if resistance is not None:
        resistance_strike = float(resistance['strike'])
        signals.append({
            "type": "resistance", "title": "Resistance", "badge": _classify_strength(abs(float(resistance['net_gex'])), max_abs_gex),
            "description": "La dinámica de mercado cambia significativamente si se rompe este nivel",
            "level": resistance_strike, "pct_from_spot": _pct_from_spot(resistance_strike, spot),
        })

    # 4. Volatility (por debajo): put wall o zero gamma, el que esté más
    # cerca por debajo del spot -- cruzarlo hacia abajo suele destapar
    # régimen de gamma negativo (más volatilidad).
    pw1 = walls.get('pw1')
    zero_gamma = walls.get('zero_gamma')
    candidates = [lvl for lvl in [pw1, zero_gamma] if lvl and lvl < spot]
    if candidates:
        level = max(candidates)
        row = by_strike[by_strike['strike'] == level]
        magnitude = abs(float(row['net_gex'].iloc[0])) if not row.empty else max_abs_gex * 0.5
        signals.append({
            "type": "volatility_increased_below", "title": "Volatility", "badge": _classify_strength(magnitude, max_abs_gex),
            "description": "Se espera mayor volatilidad si el precio cae por debajo de este nivel",
            "level": float(level), "pct_from_spot": _pct_from_spot(level, spot),
        })

    return signals


def compute_squeeze_screener(by_strike: pd.DataFrame, spot: float, walls: dict, net_dex_total: float) -> dict:
    """Puntaje 0-100 de 'gamma squeeze alcista', compuesto por 5 factores
    normalizados a su propio máximo (25/25/25/20/5). No replica ninguna
    fórmula propietaria de terceros -- son proxies razonables usando
    exactamente los datos que esta app ya calcula (net_gex por strike,
    walls, DEX total, OI y volumen por strike vía domain/parsing.py)."""
    empty = {"direction": None, "state": None, "probability": None, "factors": [], "key_levels": {}}
    if by_strike is None or by_strike.empty or spot <= 0 or not walls.get('cw1'):
        return empty

    net_gex_total = float(by_strike['net_gex'].sum())
    cw1 = float(walls['cw1'])

    # Gamma Regime (0-25): negativo (dealers cortos gamma, compran fuerza
    # = combustible para un squeeze) = puntaje completo; positivo = 0.
    gamma_regime_score = 25.0 * _clamp(-net_gex_total / GAMMA_REGIME_REF)

    # Call Wall Proximity (0-25): más cerca del Call Wall = más puntos.
    # Si el spot ya lo superó, proximidad máxima.
    if spot >= cw1:
        cw_proximity_score = 25.0
    else:
        dist_pct = (cw1 - spot) / spot * 100.0
        cw_proximity_score = 25.0 * _clamp(1 - dist_pct / CALL_WALL_PROXIMITY_PCT_REF)

    # Flow Alignment (0-25): DEX total positivo (flujo de opciones con
    # sesgo alcista) suma a favor de la tesis.
    flow_score = 25.0 * _clamp(net_dex_total / DEX_REF)

    # Volume Confirm (0-20): ratio volumen/OI del lado calls cerca del
    # Call Wall -- actividad alta relativa al open interest ya existente
    # es la proxy de "confirmación" más razonable sin un histórico de
    # volumen propio contra el cual comparar.
    near_cw = by_strike[(by_strike['strike'] >= cw1 * 0.98) & (by_strike['strike'] <= cw1 * 1.02)]
    oi_near_cw = float(near_cw['openInterest_c'].sum()) if 'openInterest_c' in near_cw.columns else 0.0
    volume_near_cw = float(near_cw['volume_c'].sum()) if 'volume_c' in near_cw.columns else 0.0
    if not near_cw.empty and oi_near_cw > 0:
        vol_oi_ratio = volume_near_cw / oi_near_cw
        volume_score = 20.0 * _clamp(vol_oi_ratio / VOLUME_OI_RATIO_REF)
    else:
        volume_score = 0.0

    # Delta OI Alignment (0-5): sesgo de open interest calls vs puts entre
    # spot y el Call Wall -- más calls que puts ahí apoya la tesis.
    window = by_strike[(by_strike['strike'] >= spot) & (by_strike['strike'] <= cw1)]
    oi_c = float(window['openInterest_c'].sum()) if 'openInterest_c' in window.columns else 0.0
    oi_p = float(window['openInterest_p'].sum()) if 'openInterest_p' in window.columns else 0.0
    total_oi = oi_c + oi_p
    if total_oi > 0:
        call_skew = (oi_c - oi_p) / total_oi
        delta_oi_score = 5.0 * _clamp((call_skew + 1) / 2)
    else:
        delta_oi_score = 0.0

    probability = gamma_regime_score + cw_proximity_score + flow_score + volume_score + delta_oi_score

    if probability >= 75:
        state = "IMMINENT"
    elif probability >= 50:
        state = "LIKELY"
    elif probability >= 25:
        state = "POSSIBLE"
    else:
        state = "UNLIKELY"

    trigger = _nearest_resistance_above(by_strike, spot)
    trigger_level = float(trigger['strike']) if trigger is not None else cw1

    return {
        "direction": "Bullish Squeeze",
        "bias": "BULLISH" if (net_gex_total <= 0 or net_dex_total >= 0) else "NEUTRAL",
        "state": state,
        "probability": round(probability),
        "factors": [
            {"label": "Gamma Regime", "score": round(gamma_regime_score), "max": 25},
            {"label": "Call Wall Proximity", "score": round(cw_proximity_score), "max": 25},
            {"label": "Flow Alignment", "score": round(flow_score), "max": 25},
            {"label": "Volume Confirm", "score": round(volume_score), "max": 20},
            {"label": "Delta OI Alignment", "score": round(delta_oi_score), "max": 5},
        ],
        "key_levels": {
            "current_price": spot,
            "call_wall": cw1,
            "call_wall_pct": _pct_from_spot(cw1, spot),
            "trigger_level": trigger_level,
        },
    }
