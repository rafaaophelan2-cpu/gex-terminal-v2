import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d

from app.domain.drift import DEFAULT_SESSION_END, DEFAULT_SESSION_START
from app.domain.gex_math import compute_call_put_walls, compute_zero_crossing

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
    value_key: str = 'net_gex',
) -> dict:
    """Matriz strike x tiempo de un valor real por strike (net_gex por
    defecto, o net_chex para el panel de Charm Heatmap -- ver
    compute_charm_heatmap_matrix abajo), construida directo de los
    snapshots que snapshot_writer ya guarda -- a diferencia de
    compute_z_matrix_cached en app.py (que recalculaba Black-Scholes sobre
    una grilla sintética de strikes finos con un doble `for` en Python
    puro), esto reusa el valor real ya calculado por cada snapshot, sin
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
            value = float(item.get(value_key, 0.0) or 0.0)
            for row, weight in band_weights_by_strike.get(strike, {}).items():
                z[row, t_idx] = value * weight

    if z.shape[1] > 1:
        z = gaussian_filter1d(z, sigma=TIME_SIGMA, axis=1)

    return {"times": times, "strikes": y_axis, "z": z.tolist(), "spot": spots}


def compute_charm_heatmap_matrix(
    snapshots: list[dict],
    session_start: str = DEFAULT_SESSION_START,
    session_end: str = DEFAULT_SESSION_END,
) -> dict:
    """Igual que compute_heatmap_matrix pero con net_chex (Charm Exposure)
    en vez de net_gex -- panel de Charm Heatmap (ver Aleks Rosme: el
    'drift' direccional que el paso del tiempo fuerza en el hedging de
    dealers, independiente del movimiento de precio). Snapshots guardados
    antes de que snapshot_writer empezara a incluir 'net_chex' por strike
    simplemente aportan 0 en esas columnas, no rompen la matriz."""
    return compute_heatmap_matrix(snapshots, session_start, session_end, value_key='net_chex')


def _strike_frame(snap: dict, value_key: str) -> pd.DataFrame:
    """DataFrame chico strike/'value_key' a partir de snap['strikes'] --
    misma forma que espera compute_call_put_walls/compute_zero_crossing
    (una fila por strike), armado en memoria sin tocar la red ni
    Black-Scholes: cada snapshot ya trae el valor real por strike."""
    rows = [
        {"strike": float(item["strike"]), value_key: float(item.get(value_key, 0.0) or 0.0)}
        for item in snap.get("strikes", [])
    ]
    return pd.DataFrame(rows, columns=["strike", value_key])


def compute_gamma_trend_lines(
    snapshots: list[dict],
    session_start: str = DEFAULT_SESSION_START,
    session_end: str = DEFAULT_SESSION_END,
) -> dict:
    """Gamma Peak (Call Wall dominante), Gamma Trough (Put Wall dominante)
    y Gamma Zero (Zero Gamma) de CADA instante, para dibujar como líneas
    de tendencia superpuestas al heatmap de LIVE GAMMA -- igual que el
    panel 'Gamma' de la herramienta de Aleks Rosme (líneas verde/amarilla/
    azul). A diferencia de compute_heatmap_matrix (que solo pinta
    intensidad de color), acá se recalculan Call Wall/Put Wall/Zero Gamma
    REALES por snapshot a partir de los mismos datos ya guardados -- sin
    proyectar ninguna extrapolación hacia el futuro (el 'cono' punteado de
    la herramienta original es una extrapolación visual de esa
    herramienta, no un dato real; acá solo se grafica la serie histórica
    real)."""
    filtered = [s for s in snapshots if session_start <= s.get('time', '') <= session_end]
    if not filtered:
        return {"times": [], "gamma_peak": [], "gamma_trough": [], "gamma_zero": []}

    times: list[str] = []
    gamma_peak: list[float] = []
    gamma_trough: list[float] = []
    gamma_zero: list[float] = []

    for snap in filtered:
        spot = float(snap.get('spot', 0.0))
        df = _strike_frame(snap, 'net_gex')
        cw1, _, _, pw1, _, _ = compute_call_put_walls(df, spot)
        zero_gamma = compute_zero_crossing(df, 'net_gex', spot)

        times.append(snap.get('time', ''))
        gamma_peak.append(cw1)
        gamma_trough.append(pw1)
        gamma_zero.append(zero_gamma)

    return {"times": times, "gamma_peak": gamma_peak, "gamma_trough": gamma_trough, "gamma_zero": gamma_zero}


def compute_charm_trend_line(
    snapshots: list[dict],
    session_start: str = DEFAULT_SESSION_START,
    session_end: str = DEFAULT_SESSION_END,
) -> dict:
    """Charm Zero de cada instante (strike donde el Charm Exposure
    acumulado cruza cero) -- única línea de tendencia que Aleks Rosme
    dibuja sobre su panel de Charm (a diferencia del de Gamma, ahí no hay
    Peak/Trough, solo la línea de cruce por cero)."""
    filtered = [s for s in snapshots if session_start <= s.get('time', '') <= session_end]
    if not filtered:
        return {"times": [], "charm_zero": []}

    times: list[str] = []
    charm_zero: list[float] = []

    for snap in filtered:
        spot = float(snap.get('spot', 0.0))
        df = _strike_frame(snap, 'net_chex')
        charm_zero.append(compute_zero_crossing(df, 'net_chex', spot))
        times.append(snap.get('time', ''))

    return {"times": times, "charm_zero": charm_zero}
