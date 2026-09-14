import pandas as pd


def _fmt_num(value: float) -> str:
    """720.00 -> '720', 717.50 -> '717.5' -- números limpios como en el
    formato de referencia del usuario, sin ceros de más."""
    return f"{value:.2f}".rstrip('0').rstrip('.')


def compute_dominant_gamma_wall(by_strike: pd.DataFrame) -> float | None:
    """"Gamma Wall": el strike con mayor GEX TOTAL de toda la cadena --
    |call_gex| + |put_gex|, NO |net_gex|. Un strike con muchísimo call_gex
    Y muchísimo put_gex que casi se cancelan (net_gex chico) sigue siendo
    un punto de altísima actividad de hedging de dealers en AMBOS lados,
    y esta métrica lo refleja; net_gex ahí lo escondería por completo.
    A diferencia de Zero Gamma/Gamma Flip (dónde el gamma acumulado NETO
    cruza cero), esto es DÓNDE se concentra más gamma en términos brutos,
    sea del lado call, put, o ambos. Puede coincidir con CW1 o PW1 (el que
    sea más dominante de los dos) o no coincidir con ninguno."""
    if by_strike is None or by_strike.empty or 'call_gex' not in by_strike.columns or 'put_gex' not in by_strike.columns:
        return None
    total_gex = by_strike['call_gex'].abs() + by_strike['put_gex'].abs()
    idx = total_gex.idxmax()
    return float(by_strike.loc[idx, 'strike'])


def build_tradingview_levels_string(ticker: str, walls: dict, zero_gamma: float, dominant_wall: float | None) -> str:
    """Arma el string en el formato que espera el indicador de Pine Script
    "Gamma Levels para TradingView" (ver frontend, sección Utilidad):
    '$TICKER!: Nombre, valor, Nombre, valor, ..., Nombre, valor.'
    -- SIEMPRE en la escala nativa del ticker de opciones (QQQ, SPY, etc.),
    nunca convertido a puntos de futuros: esa conversión la hace el propio
    indicador de Pine con el ratio en vivo entre el futuro y el ETF/índice,
    igual que su 'Conversion Engine' original."""
    pairs = [
        ("Call Wall 1", walls.get('cw1')), ("Call Wall 2", walls.get('cw2')), ("Call Wall 3", walls.get('cw3')),
        ("Put Wall 1", walls.get('pw1')), ("Put Wall 2", walls.get('pw2')), ("Put Wall 3", walls.get('pw3')),
        ("Gamma Flip", zero_gamma), ("Gamma Wall", dominant_wall),
    ]
    # 'value == value' descarta NaN además de None -- 'is not None' solo
    # no alcanza porque NaN "is not None" es True, así que un wall NaN
    # (dato corrupto río arriba) se colaba y _fmt_num lo formateaba como
    # el string literal "nan" dentro del string que consume el indicador
    # de Pine Script, en vez de omitirse como cualquier otro nivel ausente.
    body = ", ".join(f"{name}, {_fmt_num(value)}" for name, value in pairs if value is not None and value == value)
    return f"${ticker}!: {body}."
