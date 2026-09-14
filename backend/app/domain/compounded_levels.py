from dataclasses import dataclass

# 0.3% del spot primario -- suficientemente ajustado para no dar falsos
# positivos entre dos libros de opciones distintos, suficientemente ancho
# para tolerar el redondeo propio de traducir un nivel de un subyacente
# a otro por ratio de spot.
COMPOUND_TOLERANCE_PCT = 0.003


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
) -> list[CompoundedLevel]:
    """Niveles "compuestos": cuando dos pools de open interest
    independientes sobre el MISMO mercado subyacente (ej. QQQ y NDX,
    ambos sobre Nasdaq-100) muestran gamma grande en el mismo precio
    traducido, ese nivel tiene más peso que uno que aparece en un solo
    libro -- es el "bread and butter" del framework de Aleks Rosme:
    cruzar SIEMPRE ambos mapas antes de darle prioridad a un nivel.

    primary_levels/secondary_levels: dict[nombre legible -> valor o
    None]. Un mismo nivel primario puede coincidir con más de un nivel
    secundario (poco común, pero no se descarta)."""
    if ratio <= 0 or primary_spot <= 0:
        return []

    tolerance = primary_spot * COMPOUND_TOLERANCE_PCT

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
