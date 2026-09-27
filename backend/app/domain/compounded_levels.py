from dataclasses import dataclass

# Medio strike del primario (QQQ/SPY: strikes de 1 USD cerca del spot). Antes
# era el 0.3% del spot: con QQQ en ~740 eso daba ±2.2 USD (~90 puntos de MNQ,
# más de 4 strikes de ancho) y el 26-sep-2026 los 8 niveles de NDX
# "coincidían" con el mismo nivel de QQQ -- un compuesto que siempre aparece
# no aporta convicción. Con medio strike, coincidir es caer en el MISMO strike
# de QQQ una vez traducido, que es lo que el framework entiende por "dos
# libros con gamma grande en el mismo precio".
COMPOUND_TOLERANCE_USD = 0.5


@dataclass
class CompoundedLevel:
    primary_name: str
    primary_value: float
    secondary_name: str
    secondary_value_translated: float


def translate_level(value: float, ratio: float) -> float:
    """ratio = spot_secundario / spot_primario -- convierte un nivel del
    libro SECUNDARIO (ej. NDX) a la escala de precio del PRIMARIO (ej.
    QQQ), el mismo tipo de conversión que ya usa el indicador de
    TradingView para NQ/MNQ, pero entre dos chains de opciones en vez de
    entre ETF y futuro."""
    if ratio <= 0:
        return value
    return value / ratio


def find_compounded_levels(
    primary_levels: dict[str, float | None],
    secondary_levels: dict[str, float | None],
    ratio: float,
    primary_spot: float,
    tolerance: float | None = None,
) -> list[CompoundedLevel]:
    """Niveles "compuestos": cuando dos pools de open interest
    independientes sobre el MISMO mercado subyacente (ej. QQQ y NDX,
    ambos sobre Nasdaq-100) muestran gamma grande en el mismo precio
    traducido, ese nivel tiene más peso que uno que aparece en un solo
    libro -- es el "bread and butter" del framework de Aleks Rosme:
    cruzar SIEMPRE ambos mapas antes de darle prioridad a un nivel.

    primary_levels/secondary_levels: dict[nombre legible -> valor o
    None]. 'tolerance' en USD del primario (default: medio strike, ver
    COMPOUND_TOLERANCE_USD). Un mismo nivel primario puede coincidir con más de un nivel
    secundario (poco común, pero no se descarta)."""
    if ratio <= 0 or primary_spot <= 0:
        return []

    tolerance = COMPOUND_TOLERANCE_USD if tolerance is None else tolerance

    # Dos niveles primarios distintos (ej. Zero Gamma y Gamma Wall) a
    # veces caen en el MISMO precio -- sin agrupar acá, el cruce de abajo
    # los trata como entradas independientes y cada nivel NDX coincidente
    # sale duplicado, una vez por cada nombre primario (reportado en
    # vivo: "Zero Gamma (715.00) = Call Wall 1 NDX" y "Gamma Wall (715.00)
    # = Call Wall 1 NDX" mostrando el MISMO número dos veces). Se agrupan
    # por valor (redondeado a centavos, la precisión real de un precio)
    # ANTES de cruzar, combinando sus nombres en una sola fila.
    grouped_primary: dict[float, list[str]] = {}
    for p_name, p_val in primary_levels.items():
        if p_val is None:
            continue
        grouped_primary.setdefault(round(p_val, 2), []).append(p_name)

    out: list[CompoundedLevel] = []
    for p_val, p_names in grouped_primary.items():
        combined_name = " / ".join(p_names)
        for s_name, s_val in secondary_levels.items():
            if s_val is None:
                continue
            s_translated = translate_level(s_val, ratio)
            if abs(p_val - s_translated) <= tolerance:
                out.append(CompoundedLevel(combined_name, p_val, s_name, s_translated))
    return out
