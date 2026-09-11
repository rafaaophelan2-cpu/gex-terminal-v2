import numpy as np
from scipy.ndimage import gaussian_filter

from app.domain.drift import DEFAULT_SESSION_END, DEFAULT_SESSION_START

# Sigma del blur gaussiano (en unidades de índice de la matriz, no en
# strikes/minutos reales): (eje strike, eje tiempo). Asimétrico a
# propósito: en el eje strike se mantiene bajo para que niveles
# adyacentes (~$1 de separación real, no la grilla sintética fina de
# app.py) sigan siendo distinguibles como bandas separadas -- con 0.6 en
# ambos ejes (valor anterior) más el zsmooth de Plotly encima, el
# resultado terminaba siendo un solo bloque de color sin bandas
# reconocibles. El eje tiempo puede llevar algo más para el efecto
# "glow" horizontal sin que eso implique mezclar strikes entre sí.
BLUR_SIGMA = (0.35, 0.5)


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
        z = gaussian_filter(z, sigma=BLUR_SIGMA)

    return {"times": times, "strikes": strikes_sorted, "z": z.tolist(), "spot": spots}
