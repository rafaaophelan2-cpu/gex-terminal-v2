import numpy as np
from scipy.ndimage import gaussian_filter1d

from app.domain.drift import DEFAULT_SESSION_END, DEFAULT_SESSION_START

# Cada nivel se dibuja como una banda angosta y FIJA de ±BAND_HALF_WIDTH
# puntos de precio alrededor del strike real -- no como una fila que
# ocupa todo el espacio hasta el strike vecino (comportamiento por
# defecto de un heatmap: Plotly ubica el límite de cada celda en el
# punto medio con su vecina en el eje Y). Con eso, dos strikes reales
# separados por más de 2*BAND_HALF_WIDTH quedan con una franja vacía
# (transparente) entre ambos: áreas pequeñas y separadas, no un bloque
# continuo pegado al de al lado.
BAND_HALF_WIDTH = 0.2
# Margen mínimo justo afuera de la banda, con valor 0 -- fuerza el borde
# de la banda a ser nítido en vez de que Plotly interpole el límite de
# la celda hasta la mitad de camino al próximo punto del eje Y.
EDGE_MARGIN = 0.02

# El eje Y ahora es irregular (pocos puntos por strike, no una grilla
# fina uniforme) para no inflar el payload -- un sigma en "unidades de
# índice" no correspondería a una distancia de precio consistente ahí.
# El suavizado se aplica solo en el eje tiempo (columnas, sí uniforme),
# dejando cada banda con bordes nítidos y su ancho exacto en precio.
TIME_SIGMA = 0.6


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
    el free tier de 0.1 vCPU de Render."""
    filtered = [s for s in snapshots if session_start <= s.get('time', '') <= session_end]
    if not filtered:
        return {"times": [], "strikes": [], "z": [], "spot": []}

    strikes_set: set[float] = set()
    for snap in filtered:
        for item in snap.get('strikes', []):
            strikes_set.add(float(item['strike']))
    if not strikes_set:
        return {"times": [], "strikes": [], "z": [], "spot": []}

    real_strikes = sorted(strikes_set)

    # Eje Y combinado: 4 puntos por strike real (borde exterior en 0,
    # borde de la banda, y los dos bordes simétricos del lado opuesto),
    # deduplicados y ordenados. band_rows_by_strike guarda, para cada
    # strike, qué índices de ese eje caen DENTRO de su banda (reciben el
    # valor real) -- todo lo demás queda en 0 (transparente).
    y_points: set[float] = set()
    for s in real_strikes:
        y_points.add(round(s - BAND_HALF_WIDTH - EDGE_MARGIN, 4))
        y_points.add(round(s - BAND_HALF_WIDTH, 4))
        y_points.add(round(s + BAND_HALF_WIDTH, 4))
        y_points.add(round(s + BAND_HALF_WIDTH + EDGE_MARGIN, 4))
    y_axis = sorted(y_points)

    band_rows_by_strike: dict[float, list[int]] = {}
    for s in real_strikes:
        lo, hi = s - BAND_HALF_WIDTH - 1e-9, s + BAND_HALF_WIDTH + 1e-9
        band_rows_by_strike[s] = [i for i, y in enumerate(y_axis) if lo <= y <= hi]

    times = [snap.get('time', '') for snap in filtered]
    spots = [float(snap.get('spot', 0.0)) for snap in filtered]
    z = np.zeros((len(y_axis), len(filtered)))

    for t_idx, snap in enumerate(filtered):
        for item in snap.get('strikes', []):
            strike = float(item['strike'])
            value = float(item.get('net_gex', 0.0))
            for row in band_rows_by_strike.get(strike, ()):
                z[row, t_idx] = value

    if z.shape[1] > 1:
        z = gaussian_filter1d(z, sigma=TIME_SIGMA, axis=1)

    return {"times": times, "strikes": y_axis, "z": z.tolist(), "spot": spots}
