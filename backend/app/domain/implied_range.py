import math
from datetime import datetime, time
from zoneinfo import ZoneInfo

# Cierre real de NYSE/Nasdaq en hora LOCAL de NY (16:00 SIEMPRE, sin
# ambigüedad de horario de verano) -- mismo patrón ya usado en
# services/tradingview_string_updater.py (STRING_WINDOW_END) para lo mismo.
NY_TZ = ZoneInfo("America/New_York")
# Límite conocido (code review 2026-09-18): NO contempla los ~4 días/año de
# cierre anticipado (13:00 ET -- víspera de Thanksgiving, 3 de julio,
# Nochebuena) -- en esos días esto sobreestima el tiempo real a expiración
# por hasta 3h. No es una regresión (el piso fijo viejo ya estaba mal
# TODOS los días), pero sigue sin ser 100% exacto en esas fechas puntuales;
# arreglarlo bien requeriría un calendario de feriados/cierres, fuera del
# alcance de este fix.
MARKET_CLOSE = time(16, 0)

# Piso mínimo de la fracción de día para 0DTE -- solo para evitar un
# expected_move de 0/negativo si esto se llama ya pasado el cierre (no
# debería pasar en producción con un feed activo), NO para moldear la
# magnitud como hacía el viejo piso fijo de 0.1 días.
MIN_DAY_FRACTION = 1.0 / 1440.0  # 1 minuto


def _day_fraction_to_close(now: datetime | None) -> float:
    """Fracción del día calendario (0-1) que falta hasta el cierre de
    mercado (16:00 hora NY) VISTO DESDE 'now' -- reemplaza el piso fijo de
    0.1 días que antes se usaba para cualquier 0DTE sin importar la hora
    real (ver gex_terminal_v2_lessons: a las 9:31am y a las 3:55pm el
    expected_move salía IDÉNTICO, cuando debería achicarse a medida que se
    acerca el cierre).

    Un 'now' SIN tzinfo se trata como si YA fuera hora de pared de NY (no
    se reinterpreta contra la zona local del sistema/server) -- evita que
    un server en UTC (Render) desalinee el cálculo en varias horas sin
    ningún error visible si algún caller futuro arma un 'now' naive."""
    now = now or datetime.now(NY_TZ)
    now = now.replace(tzinfo=NY_TZ) if now.tzinfo is None else now.astimezone(NY_TZ)
    close_dt = datetime.combine(now.date(), MARKET_CLOSE, tzinfo=NY_TZ)
    remaining_seconds = (close_dt - now).total_seconds()
    return max(remaining_seconds / 86400.0, MIN_DAY_FRACTION)


def compute_implied_range(spot: float, atm_iv: float, dte: float, now: datetime | None = None) -> dict:
    """"Implied Range": banda de movimiento esperado de la sesión a partir
    de la IV ATM de la expiración más cercana -- Aleks Rosme la usa como
    techo/piso adicional a los niveles de gamma, calculada desde la
    estructura de IV ATM de 0DTE (ancla en desviaciones estándar, no en
    un nivel de OI). expected_move = spot * IV_ATM * sqrt(DTE/365) es la
    fórmula estándar de "expected move" de un ATM straddle.

    dte en días calendario (no de mercado). Si dte<=0 (mismo día, 0DTE) el
    tiempo a expiración se calcula desde la fracción REAL del día que falta
    hasta el cierre de mercado (ver _day_fraction_to_close), no un piso fijo
    -- 'now' es inyectable para tests, por defecto la hora actual en NY."""
    if spot <= 0 or atm_iv <= 0:
        return {"expected_move": None, "one_sd": None, "two_sd": None}

    dte_years = (_day_fraction_to_close(now) if dte <= 0 else dte) / 365.0
    expected_move = spot * atm_iv * math.sqrt(dte_years)

    return {
        "expected_move": expected_move,
        "one_sd": {"low": spot - expected_move, "high": spot + expected_move},
        "two_sd": {"low": spot - 2 * expected_move, "high": spot + 2 * expected_move},
    }
