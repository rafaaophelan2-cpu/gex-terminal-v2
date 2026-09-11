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
BAND_HALF_WIDTH = 0.1
# Margen mínimo justo afuera de la banda, con peso 0 -- fuerza el borde
# exterior a ser nítido en vez de que Plotly interpole el límite de la
# celda hasta la mitad de camino al próximo punto del eje Y.
EDGE_MARGIN = 0.02

# Perfil de pesos (offset relativo al strike -> peso 0-1) que define la
# FORMA de cada nivel: sube y baja gradualmente en vez de un bloque
# rectangular con bordes duros (peso 1 de golpe) -- así el nivel se ve
# como una forma suave (tipo campana achatada) en vez de un rectángulo,
# sin depender de un blur sobre un eje irregular (que sería inconsistente
# entre niveles con distinto espaciado a su vecino).
_BAND_PROFILE = [
    (-BAND_HALF_WIDTH - EDGE_MARGIN, 0.0),
    (-BAND_HALF_WIDTH, 0.12),
    (-BAND_HALF_WIDTH * 0.5, 0.55),
    (0.0, 1.0),
    (BAND_HALF_WIDTH * 0.5, 0.55),
    (BAND_HALF_WIDTH, 0.12),
    (BAND_HALF_WIDTH + EDGE_MARGIN, 0.0),
]

# Suavizado adicional solo en el eje tiempo (columnas, sí uniforme) --
# glow horizontal suave sin afectar el ancho/forma exacta de la banda.
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

    # Eje Y combinado: los puntos del _BAND_PROFILE de cada strike real,
    # deduplicados y ordenados. band_weights_by_strike guarda, para cada
    # strike, qué fila de ese eje recibe qué fracción (peso) del valor
    # real -- todo lo demás queda en 0 (transparente).
    y_points: set[float] = set()
    for s in real_strikes:
        for offset, _weight in _BAND_PROFILE:
            y_points.add(round(s + offset, 4))
    y_axis = sorted(y_points)
    y_index = {y: i for i, y in enumerate(y_axis)}

    band_weights_by_strike: dict[float, dict[int, float]] = {}
    for s in real_strikes:
        band_weights_by_strike[s] = {
            y_index[round(s + offset, 4)]: weight for offset, weight in _BAND_PROFILE
        }

    times = [snap.get('time', '') for snap in filtered]
    spots = [float(snap.get('spot', 0.0)) for snap in filtered]
    z = np.zeros((len(y_axis), len(filtered)))

    for t_idx, snap in enumerate(filtered):
        for item in snap.get('strikes', []):
            strike = float(item['strike'])
            value = float(item.get('net_gex', 0.0))
            for row, weight in band_weights_by_strike.get(strike, {}).items():
                z[row, t_idx] = value * weight

    if z.shape[1] > 1:
        z = gaussian_filter1d(z, sigma=TIME_SIGMA, axis=1)

    return {"times": times, "strikes": y_axis, "z": z.tolist(), "spot": spots}
