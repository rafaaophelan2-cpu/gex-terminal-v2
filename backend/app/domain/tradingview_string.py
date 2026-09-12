import pandas as pd


def _fmt_num(value: float) -> str:
    """720.00 -> '720', 717.50 -> '717.5' -- números limpios como en el
    formato de referencia del usuario, sin ceros de más."""
    return f"{value:.2f}".rstrip('0').rstrip('.')


def compute_dominant_gamma_wall(by_strike: pd.DataFrame) -> float | None:
    """"Gamma Wall": el strike con mayor |net_gex| de toda la cadena --
    a diferencia de Zero Gamma/Gamma Flip (dónde el gamma acumulado
    cruza cero), esto es DÓNDE se concentra más gamma en un solo punto,
    sea del lado call o put. Puede coincidir con CW1 o PW1 (el que sea
    más dominante de los dos) o no coincidir con ninguno si hay un
    strike intermedio con más concentración que ambos extremos."""
    if by_strike is None or by_strike.empty or 'net_gex' not in by_strike.columns:
        return None
    idx = by_strike['net_gex'].abs().idxmax()
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
    body = ", ".join(f"{name}, {_fmt_num(value)}" for name, value in pairs if value is not None)
    return f"${ticker}!: {body}."
