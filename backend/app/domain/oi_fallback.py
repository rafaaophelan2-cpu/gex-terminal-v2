import pandas as pd


def apply_volume_fallback_if_no_oi(df: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Algunos subyacentes (NDX, SPX, VIX -- productos de índice
    exclusivos de CBOE) no traen Open Interest real desde Schwab: todos
    los contratos vuelven con openInterest=0 aunque sí tengan bid/ask/
    volumen/griegas reales (confirmado en vivo contra la API real: 0 de
    cientos de contratos con OI>0 en NDX/SPX/VIX, contra ~90% en QQQ/SPY
    en el mismo instante -- no es un tema de horario/fin de semana, ver
    la comparación). Sin OI, gamma exposure (gamma * OI) da CERO en
    absolutamente todos los strikes: gráfico vacío, y compute_call_put_walls/
    compute_zero_gamma caen a su fallback aritmético (spot ± N) en vez de
    niveles reales.

    Cuando se detecta esta condición (OI total = 0 en TODA la cadena), se
    sustituye openInterest_c/openInterest_p por volume_c/volume_p -- no es
    lo mismo que posicionamiento acumulado real (el volumen es la
    actividad de HOY, no la posición abierta acumulada), pero al menos
    refleja actividad real en vez de nada. Se devuelve un flag para que
    downstream (UI, prompt de la IA) puedan avisar que el número es una
    aproximación, no el GEX real basado en OI."""
    if df.empty or 'openInterest_c' not in df.columns or 'openInterest_p' not in df.columns:
        return df, False

    total_oi = df['openInterest_c'].sum() + df['openInterest_p'].sum()
    if total_oi > 0:
        return df, False

    if 'volume_c' not in df.columns or 'volume_p' not in df.columns:
        return df, False

    df_out = df.copy()
    df_out['openInterest_c'] = df_out['volume_c']
    df_out['openInterest_p'] = df_out['volume_p']
    return df_out, True
