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


def compute_volume_premium_drift_series(
    snapshots: list[dict],
    session_start: str = DEFAULT_SESSION_START,
    session_end: str = DEFAULT_SESSION_END,
    otm_only: bool = False,
) -> dict:
    """PROTOTIPO/EXPERIMENTAL -- proxy de Net Drift a partir de PREMIUM
    REAL operado (delta de 'volume_c'/'volume_p' entre snapshots
    consecutivos, valorizado al 'mark_c'/'mark_p' de ese momento), en vez
    de Open Interest recalculado como compute_drift_series de arriba.
    Pedido explícito del usuario (14-sep-2026) para comparar en vivo
    contra un Net Drift real (Aleks Rosme/QuantData) antes de decidir si
    reemplaza o convive con el de arriba -- por eso queda como un modo
    SEPARADO, no pisa compute_drift_series.

    Limitación estructural conocida, no arreglable sin un feed de trades
    real (OPRA): esto NO sabe si el volumen nuevo fue compra o venta
    agresiva -- solo sabe cuánto premium se operó en calls y en puts en
    ese intervalo. El Net Drift real clasifica cada trade contra el
    bid/ask. La MAGNITUD sí sale de volumen real operado (no de un
    recálculo de OI), pero la DIRECCIÓN es más ruidosa que el original.

    Requiere que cada snapshot traiga 'strikes[].volume_c/volume_p/
    mark_c/mark_p' (agregado en snapshot_writer.py el 14-sep-2026) --
    snapshots viejos sin esos campos, o el primer snapshot del día (no
    hay snapshot anterior con el que sacar un delta), simplemente no
    aportan al primer punto de la serie."""
    filtered = sorted(
        (s for s in snapshots if session_start <= s.get('time', '') <= session_end),
        key=lambda s: s.get('time', ''),
    )

    times: list[str] = []
    spots: list[float] = []
    call_premium: list[float] = []
    put_premium: list[float] = []
    net_premium: list[float] = []

    cum_call = 0.0
    cum_put = 0.0
    prev_by_strike: dict[float, dict] | None = None

    for snap in filtered:
        strikes = snap.get('strikes') or []
        curr_by_strike = {
            float(s['strike']): s for s in strikes
            if 'volume_c' in s and 'volume_p' in s and 'mark_c' in s and 'mark_p' in s
        }
        snap_spot = float(snap.get('spot', 0.0))

        if prev_by_strike is not None:
            for strike, curr in curr_by_strike.items():
                prev = prev_by_strike.get(strike)
                if prev is None:
                    continue

                if not otm_only or strike >= snap_spot:
                    dvol_c = int(curr['volume_c']) - int(prev['volume_c'])
                    if dvol_c > 0:
                        cum_call += dvol_c * float(curr['mark_c']) * 100.0

                if not otm_only or strike <= snap_spot:
                    dvol_p = int(curr['volume_p']) - int(prev['volume_p'])
                    if dvol_p > 0:
                        cum_put += dvol_p * float(curr['mark_p']) * 100.0

            times.append(snap.get('time', ''))
            spots.append(snap_spot)
            call_premium.append(cum_call)
            put_premium.append(-cum_put)
            net_premium.append(cum_call - cum_put)

        prev_by_strike = curr_by_strike

    return {
        "time": times,
        "spot": spots,
        "call_gex": call_premium,
        "put_gex": put_premium,
        "net_gex": net_premium,
    }
