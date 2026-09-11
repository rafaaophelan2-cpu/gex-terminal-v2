from app.domain.drift import DEFAULT_SESSION_END, DEFAULT_SESSION_START


def compute_heatmap_matrix(
    snapshots: list[dict],
    session_start: str = DEFAULT_SESSION_START,
    session_end: str = DEFAULT_SESSION_END,
) -> dict:
    """Matriz strike x tiempo de net_gex real, construida directo de los
    snapshots que snapshot_writer ya guarda -- a diferencia de
    compute_z_matrix_cached en app.py (que recalculaba Black-Scholes sobre
    una grilla sintética de strikes finos con un doble `for` en Python
    puro), esto reusa el net_gex real ya calculado por cada snapshot, sin
    volver a tocar Black-Scholes. Mucho más barato en CPU -- relevante en
    el free tier de 0.1 vCPU de Render -- y son datos reales, no una
    reconstrucción suavizada con gaussiana."""
    filtered = [s for s in snapshots if session_start <= s.get('time', '') <= session_end]
    if not filtered:
        return {"times": [], "strikes": [], "z": [], "spot": []}

    strikes_set: set[float] = set()
    for snap in filtered:
        for item in snap.get('strikes', []):
            strikes_set.add(float(item['strike']))
    strikes_sorted = sorted(strikes_set)
    strike_idx = {k: i for i, k in enumerate(strikes_sorted)}

    times = [snap.get('time', '') for snap in filtered]
    spots = [float(snap.get('spot', 0.0)) for snap in filtered]
    z = [[0.0] * len(filtered) for _ in strikes_sorted]

    for t_idx, snap in enumerate(filtered):
        for item in snap.get('strikes', []):
            row = strike_idx[float(item['strike'])]
            z[row][t_idx] = float(item.get('net_gex', 0.0))

    return {"times": times, "strikes": strikes_sorted, "z": z, "spot": spots}
