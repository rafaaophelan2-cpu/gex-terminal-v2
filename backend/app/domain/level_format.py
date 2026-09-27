"""Formato de niveles (walls, flip) que pueden no existir.

Desde el 26-sep-2026 compute_call_put_walls/compute_zero_gamma/
compute_gamma_wall devuelven None cuando el nivel no existe, en vez de
inventar uno (spot ± N, o el spot mismo). Todo texto que los interpola
(prompt de la IA, diagnóstico local, briefing) pasa por acá para no
romper con un None y para decirlo en palabras.
"""

MISSING_LEVEL = "sin nivel real"


def fmt_level(value: float | None, spec: str = ".2f") -> str:
    if value is None or value != value:  # None o NaN
        return MISSING_LEVEL
    return format(float(value), spec)
