from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# Horarios de sesión definidos por el usuario en UTC-5 fijo (sin horario de
# verano) -- coincide con America/Lima, no con America/New_York (que en
# septiembre está en EDT, UTC-4). El indicador de Quantower
# (SessionProfilePusher.cs) usa el mismo criterio para que las claves de
# Firebase que escribe coincidan exactamente con las que el backend intenta
# leer acá.
SESSION_TZ = ZoneInfo("America/Lima")

OVERNIGHT_START = time(17, 0)   # 17:00 -- arranca la sesión Overnight
CASH_START = time(8, 30)        # 08:30 -- arranca la sesión Cash (fin de Overnight)
CASH_END = time(15, 0)          # 15:00 -- fin de la sesión Cash


def overnight_key_for(now: datetime) -> str:
    """Clave de la sesión Overnight (17:00-08:29) VIGENTE en el momento
    'now' -- si son, por ejemplo, las 03:00, la sesión Overnight vigente
    arrancó AYER a las 17:00, así que se etiqueta con la fecha de ayer
    (mismo criterio que SessionProfilePusher.cs: la sesión se identifica
    por su fecha de INICIO, no la de cierre, para que toda una sesión que
    cruza medianoche quede bajo una sola clave)."""
    now = now.astimezone(SESSION_TZ)
    start_date = now.date() if now.time() >= OVERNIGHT_START else now.date() - timedelta(days=1)
    return f"overnight_{start_date.isoformat()}"


def cash_key_for(now: datetime) -> str:
    """Clave de la sesión Cash (08:30-15:00) VIGENTE o la última cerrada."""
    now = now.astimezone(SESSION_TZ)
    session_date = now.date() if now.time() >= CASH_START else now.date() - timedelta(days=1)
    return f"cash_{session_date.isoformat()}"


def _fmt_levels(values: list[float] | None) -> str:
    if not values:
        return "ninguno"
    return ", ".join(f"{v:.2f}" for v in values)


def _fmt_outliers(outliers: list[dict] | None) -> str:
    if not outliers:
        return "ninguno"
    return ", ".join(f"{o.get('price', 0):.2f} (delta {o.get('delta', 0):+.0f})" for o in outliers)


def format_session_profile(label: str, profile: dict | None) -> str:
    """Texto para el prompt de la IA a partir de un perfil de Volume/Delta/
    TPO empujado por SessionProfilePusher.cs -- niveles en puntos de
    NQ/MNQ (nativos del indicador, no convertidos a USD del ticker de
    opciones), coherente con cómo ya se le presenta a la IA el resto de
    niveles de futuros (ver 'Ratio NQ' en build_system_prompt)."""
    if not profile:
        return f"{label}: sin datos disponibles todavía (el indicador de Quantower aún no empujó esta sesión)."

    return (
        f"{label} (niveles en puntos de NQ/MNQ):\n"
        f"  POC (Point of Control): {profile.get('poc', 0):.2f} | "
        f"VAH: {profile.get('vah', 0):.2f} | VAL: {profile.get('val', 0):.2f}\n"
        f"  HVN (nodos de alto volumen -- zonas de aceptación/imán): {_fmt_levels(profile.get('hvn'))}\n"
        f"  LVN (nodos de bajo volumen -- zonas de aceleración, el precio tiende a cruzarlas rápido): {_fmt_levels(profile.get('lvn'))}\n"
        f"  Delta outliers (flujo agresivo concentrado en un nivel puntual): {_fmt_outliers(profile.get('delta_outliers'))}\n"
        f"  TPO POC: {profile.get('tpo_poc', 0):.2f} | TPO LVN: {_fmt_levels(profile.get('tpo_lvn'))}"
    )
