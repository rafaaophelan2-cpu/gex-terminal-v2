import numpy as np
from scipy.ndimage import gaussian_filter

from app.domain.drift import DEFAULT_SESSION_END, DEFAULT_SESSION_START

# Técnica "núcleo + halo" (como un glow/bloom de diseño gráfico) en vez
# de un único blur gaussiano: CORE_SIGMA mantiene el nivel angosto y
# preciso (un blur mínimo, casi nulo en el eje strike), GLOW_SIGMA genera
# un halo ancho y suave alrededor a baja intensidad (GLOW_WEIGHT), y se
# suman. Un solo blur con sigma grande (probado antes) difuminaba TODO
# el nivel por igual -- ensanchaba el bloque en vez de solo suavizar su
# borde -- que es exactamente lo contrario de "delgado y preciso pero
# con más difuminado". Unidades en índice de la matriz, no en strikes
# reales/minutos.
CORE_SIGMA = (0.12, 0.35)
GLOW_SIGMA = (1.4, 1.4)
GLOW_WEIGHT = 0.55


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
    el free tier de 0.1 vCPU de Render -- y son datos reales, con un blur
    gaussiano moderado encima (BLUR_SIGMA) solo para el efecto visual de
    "glow" suave, igual intención que app.py pero con menos intensidad al
    no tener una grilla sintética fina de por medio."""
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
    z = np.zeros((len(strikes_sorted), len(filtered)))

    for t_idx, snap in enumerate(filtered):
        for item in snap.get('strikes', []):
            row = strike_idx[float(item['strike'])]
            z[row, t_idx] = float(item.get('net_gex', 0.0))

    if z.shape[0] > 1 and z.shape[1] > 1:
        core = gaussian_filter(z, sigma=CORE_SIGMA)
        glow = gaussian_filter(z, sigma=GLOW_SIGMA)
        z = core + GLOW_WEIGHT * glow

    return {"times": times, "strikes": strikes_sorted, "z": z.tolist(), "spot": spots}
