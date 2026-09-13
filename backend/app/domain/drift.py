DEFAULT_SESSION_START = "09:30"
DEFAULT_SESSION_END = "16:00"


def compute_drift_series(
    snapshots: list[dict],
    session_start: str = DEFAULT_SESSION_START,
    session_end: str = DEFAULT_SESSION_END,
    otm_only: bool = False,
) -> dict:
    """Reconstruye la serie de NET DRIFT (Calls/Puts/Net reales, no un
    proxy de precio*volumen) sumando call_gex/put_gex por timestamp desde
    los snapshots ya guardados por snapshot_writer. Port de la
    reconstrucción de Net Drift en app.py (~línea 1740): cada snapshot
    trae su detalle por strike en 'strikes', del cual se suman call_gex y
    put_gex para ese instante.

    Filtra a horario de mercado (09:30-16:00 hora de Nueva York por
    defecto) -- 'time' ya viene como "HH:MM" en NY (STORAGE_TZ, ver
    snapshot_writer), así que una comparación de strings alcanza.

    'otm_only': réplica del toggle de Aleks Rosme entre su vista de
    "todas las strikes" (por defecto acá) y su vista "OTM" -- cuando
    viene en True, antes de sumar cada strike se descartan las calls con
    strike < spot y las puts con strike > spot (usa el spot DE ESE MISMO
    snapshot, no el spot actual, para que el filtro sea correcto en cada
    instante de la serie histórica)."""
    times: list[str] = []
    spots: list[float] = []
    call_gex: list[float] = []
    put_gex: list[float] = []
    net_gex: list[float] = []

    for snap in snapshots:
        time_str = snap.get('time', '')
        if not (session_start <= time_str <= session_end):
            continue

        snap_spot = float(snap.get('spot', 0.0))
        strikes = snap.get('strikes') or []
        if otm_only:
            call_sum = sum(float(s.get('call_gex', 0.0)) for s in strikes if float(s.get('strike', 0.0)) >= snap_spot)
            put_sum = sum(float(s.get('put_gex', 0.0)) for s in strikes if float(s.get('strike', 0.0)) <= snap_spot)
        else:
            call_sum = sum(float(s.get('call_gex', 0.0)) for s in strikes)
            put_sum = sum(float(s.get('put_gex', 0.0)) for s in strikes)

        times.append(time_str)
        spots.append(snap_spot)
        call_gex.append(call_sum)
        put_gex.append(put_sum)
        net_gex.append(call_sum + put_sum if otm_only else float(snap.get('net_gex', call_sum + put_sum)))

    return {
        "time": times,
        "spot": spots,
        "call_gex": call_gex,
        "put_gex": put_gex,
        "net_gex": net_gex,
    }
