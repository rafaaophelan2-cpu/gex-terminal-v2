from datetime import datetime, timedelta, time
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


def _to_equivalent(nq_value: float, conversion_ratio: float | None) -> float | None:
    """NQ/MNQ points -> USD equivalentes del ticker de opciones (QQQ) --
    división directa por el ratio, la MISMA fórmula que ya usa el
    indicador de Quantower (GexProfileCloud.cs) para ir en sentido
    contrario (strike * ratio = precio MNQ). Se precomputa acá, en vez
    de dejar que la IA haga la cuenta mentalmente con el ratio suelto en
    el prompt -- fue justo eso lo que causó una lectura de "alineación"
    incorrecta entre un wall en USD y un POC/VAH/VAL en puntos NQ."""
    if not conversion_ratio or conversion_ratio <= 0:
        return None
    return nq_value / conversion_ratio


def _fmt_level(value: float | None, conversion_ratio: float | None, ticker: str) -> str:
    # Antes esto crasheaba con un TypeError si 'value' era None -- un POC/
    # VAH/VAL/outlier realmente None (ej. sesión Overnight con muy poco
    # volumen, sin suficiente data todavía para calcular un Value Area)
    # tira _to_equivalent(None, ratio) -> None / ratio. Se distingue acá
    # de un valor 0.0 REAL (que sí debe formatearse normal, no es "sin
    # dato").
    if value is None:
        return "sin dato"
    equiv = _to_equivalent(value, conversion_ratio)
    if equiv is None:
        return f"{value:.2f} pts NQ/MNQ (sin ratio de conversión para comparar contra {ticker})"
    return f"{value:.2f} pts NQ/MNQ (equivalente {ticker}: {equiv:.2f})"


# Tope duro de cuántos nodos/outliers se listan en el prompt -- el
# indicador de Quantower (SessionProfilePusher.cs) puede empujar
# decenas de HVN/LVN/delta outliers en una sesión larga (Overnight dura
# 17:00-08:29), y listarlos TODOS sin límite es justo lo que hizo que el
# prompt de este sistema superara el límite de Tokens Por Minuto de la
# cuenta de Groq en producción (confirmado en vivo: un pedido de
# ~30.700 caracteres). Con el tope, "el más relevante" queda a criterio
# de lo que YA venga ordenado desde el indicador (no se reordena acá).
MAX_LEVELS_SHOWN = 6


def _fmt_levels(values: list[float] | None, conversion_ratio: float | None, ticker: str) -> str:
    if not values:
        return "ninguno"
    shown = values[:MAX_LEVELS_SHOWN]
    extra = f" (+{len(values) - MAX_LEVELS_SHOWN} más)" if len(values) > MAX_LEVELS_SHOWN else ""
    return "; ".join(_fmt_level(v, conversion_ratio, ticker) for v in shown) + extra


def _fmt_outliers(outliers: list[dict] | None, conversion_ratio: float | None, ticker: str) -> str:
    if not outliers:
        return "ninguno"
    shown = outliers[:MAX_LEVELS_SHOWN]
    parts = []
    for o in shown:
        price = o.get('price')
        delta = o.get('delta')
        # delta=None crasheaba en '{delta:+.0f}' -- mismo motivo que el
        # guard de None en _fmt_level, para un outlier con delta faltante.
        delta_str = f"{delta:+.0f}" if delta is not None else "sin dato"
        parts.append(f"{_fmt_level(price, conversion_ratio, ticker)} (delta {delta_str})")
    extra = f" (+{len(outliers) - MAX_LEVELS_SHOWN} más)" if len(outliers) > MAX_LEVELS_SHOWN else ""
    return "; ".join(parts) + extra


def format_session_profile(label: str, profile: dict | None, conversion_ratio: float | None, ticker: str = "QQQ") -> str:
    """Texto para el prompt de la IA a partir de un perfil de Volume/Delta/
    TPO empujado por SessionProfilePusher.cs -- los niveles llegan
    NATIVOS en puntos de NQ/MNQ (así los calcula el indicador, sobre el
    chart de futuros), así que cada uno se muestra CON su equivalente ya
    convertido a {ticker} (dividido por conversion_ratio) -- para que la
    IA compare directo contra sus walls/Zero Gamma (que sí están en
    {ticker}) sin tener que hacer la conversión ella misma."""
    if not profile:
        return f"{label}: sin datos disponibles todavía (el indicador de Quantower aún no empujó esta sesión)."

    # .get(key) SIN default -- antes ('poc', 0) etc.) una clave
    # genuinamente AUSENTE del payload (no None explícito, sino nunca
    # enviada) se formateaba como "0.00 pts NQ/MNQ (equivalente...: 0.00)",
    # un nivel real-pero-falso indistinguible de un POC de verdad en
    # precio cero -- directo al prompt que lee la IA. Con default None,
    # _fmt_level ahora lo muestra explícitamente como "sin dato".
    return (
        f"{label}:\n"
        f"  POC (Point of Control): {_fmt_level(profile.get('poc'), conversion_ratio, ticker)}\n"
        f"  VAH: {_fmt_level(profile.get('vah'), conversion_ratio, ticker)}\n"
        f"  VAL: {_fmt_level(profile.get('val'), conversion_ratio, ticker)}\n"
        f"  HVN (nodos de alto volumen -- zonas de aceptación/imán): {_fmt_levels(profile.get('hvn'), conversion_ratio, ticker)}\n"
        f"  LVN (nodos de bajo volumen -- zonas de aceleración, el precio tiende a cruzarlas rápido): {_fmt_levels(profile.get('lvn'), conversion_ratio, ticker)}\n"
        f"  Delta outliers (flujo agresivo concentrado en un nivel puntual): {_fmt_outliers(profile.get('delta_outliers'), conversion_ratio, ticker)}\n"
        f"  TPO POC: {_fmt_level(profile.get('tpo_poc'), conversion_ratio, ticker)}\n"
        f"  TPO LVN: {_fmt_levels(profile.get('tpo_lvn'), conversion_ratio, ticker)}"
    )
