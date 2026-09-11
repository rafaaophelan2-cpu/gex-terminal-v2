def compute_drift_series(snapshots: list[dict]) -> dict:
    """Reconstruye la serie de NET DRIFT (Calls/Puts/Net reales, no un
    proxy de precio*volumen) sumando call_gex/put_gex por timestamp desde
    los snapshots ya guardados por snapshot_writer. Port de la
    reconstrucción de Net Drift en app.py (~línea 1740): cada snapshot
    trae su detalle por strike en 'strikes', del cual se suman call_gex y
    put_gex para ese instante."""
    times: list[str] = []
    spots: list[float] = []
    call_gex: list[float] = []
    put_gex: list[float] = []
    net_gex: list[float] = []

    for snap in snapshots:
        strikes = snap.get('strikes') or []
        call_sum = sum(float(s.get('call_gex', 0.0)) for s in strikes)
        put_sum = sum(float(s.get('put_gex', 0.0)) for s in strikes)

        times.append(snap.get('time', ''))
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
