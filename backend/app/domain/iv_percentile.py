MIN_HISTORY_DAYS = 10


def compute_iv_percentile(current_atm_iv: float, historical_daily_iv: list[float]) -> str | None:
    """Percentil real de IV ATM contra un historial diario acumulado (un
    valor por día de mercado, el cierre de ese día -- ver
    fetch_daily_atm_iv_history en integrations/supabase_client.py),
    reemplazando la fórmula sintética anterior (atm_iv / 0.35, clamp
    15-85) que en realidad no leía ningún historial: solo reescalaba
    linealmente la IV del instante, así que nunca podía mostrar un
    percentil verdaderamente extremo aunque la IV real lo fuera.

    Devuelve None mientras no haya al menos MIN_HISTORY_DAYS de historial
    real todavía -- mejor no mostrar un número que fingir precisión que
    no existe con 2 o 3 días de datos."""
    if len(historical_daily_iv) < MIN_HISTORY_DAYS:
        return None

    count_at_or_below = sum(1 for iv in historical_daily_iv if iv <= current_atm_iv)
    pct = round(count_at_or_below / len(historical_daily_iv) * 100)
    return f"{pct}th percentile (histórico real, {len(historical_daily_iv)}d)"
