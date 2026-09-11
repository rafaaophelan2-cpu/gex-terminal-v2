DEFAULT_SESSION_START = "09:30"
DEFAULT_SESSION_END = "16:00"


def compute_drift_series(
    snapshots: list[dict],
    session_start: str = DEFAULT_SESSION_START,
    session_end: str = DEFAULT_SESSION_END,
) -> dict:
    """Reconstruye la serie de NET DRIFT (Calls/Puts/Net reales, no un
    proxy de precio*volumen) sumando call_gex/put_gex por timestamp desde
    los snapshots ya guardados por snapshot_writer. Port de la
    reconstrucción de Net Drift en app.py (~línea 1740): cada snapshot
    trae su detalle por strike en 'strikes', del cual se suman call_gex y
    put_gex para ese instante.

    Filtra a horario de mercado (09:30-16:00 hora de Nueva York por
    defecto) -- 'time' ya viene como "HH:MM" en NY (STORAGE_TZ, ver
    snapshot_writer), así que una comparación de strings alcanza."""
    times: list[str] = []
    spots: list[float] = []
    call_gex: list[float] = []
    put_gex: list[float] = []
    net_gex: list[float] = []

    for snap in snapshots:
        time_str = snap.get('time', '')
        if not (session_start <= time_str <= session_end):
            continue

        strikes = snap.get('strikes') or []
        call_sum = sum(float(s.get('call_gex', 0.0)) for s in strikes)
        put_sum = sum(float(s.get('put_gex', 0.0)) for s in strikes)

        times.append(time_str)
        spots.append(float(snap.get('spot', 0.0)))
        call_gex.append(call_sum)
        put_gex.append(put_sum)
        net_gex.append(float(snap.get('net_gex', call_sum + put_sum)))

    return {
        "time": times,
        "spot": spots,
        "call_gex": call_gex,
        "put_gex": put_gex,
        "net_gex": net_gex,
    }
