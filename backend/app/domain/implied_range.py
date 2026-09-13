import math


def compute_implied_range(spot: float, atm_iv: float, dte: float) -> dict:
    """"Implied Range": banda de movimiento esperado de la sesión a partir
    de la IV ATM de la expiración más cercana -- Aleks Rosme la usa como
    techo/piso adicional a los niveles de gamma, calculada desde la
    estructura de IV ATM de 0DTE (ancla en desviaciones estándar, no en
    un nivel de OI). expected_move = spot * IV_ATM * sqrt(DTE/365) es la
    fórmula estándar de "expected move" de un ATM straddle.

    dte en días calendario (no de mercado) -- si viene 0 (mismo día,
    0DTE) se usa un piso de 0.1 para no anular la banda por completo."""
    if spot <= 0 or atm_iv <= 0:
        return {"expected_move": None, "one_sd": None, "two_sd": None}

    dte_years = max(dte, 0.1) / 365.0
    expected_move = spot * atm_iv * math.sqrt(dte_years)

    return {
        "expected_move": expected_move,
        "one_sd": {"low": spot - expected_move, "high": spot + expected_move},
        "two_sd": {"low": spot - 2 * expected_move, "high": spot + 2 * expected_move},
    }
