from app.domain.ai_prompt import classify_vix
from app.domain.level_format import fmt_level


def generate_local_diagnosis(ticker: str, spot: float, metrics: dict, vix_val: float, conversion_ratio: float = 41.125) -> str:
    """Plantilla local sin LLM -- se usa cuando no hay GROQ_API_KEY o la
    llamada a Groq falla, para que la pestaña DATA nunca quede vacía.
    Port aproximado de generar_analisis_local en app.py: mismo esqueleto
    de secciones y misma regla de direccionalidad (rebote en Put Wall =
    LONG, rebote en Call Wall = SHORT), sin el razonamiento libre de un
    LLM real."""
    vix_status, vix_desc, _ = classify_vix(vix_val)
    is_positive = metrics['net_gex_total'] >= 0

    if is_positive:
        comportamiento = (
            "Los dealers están largos gamma: cada movimiento del precio los obliga a cubrirse en "
            "dirección contraria, lo que **amortigua** la volatilidad y favorece rangos/mean-reversion."
        )
    else:
        comportamiento = (
            "Los dealers están cortos gamma: cada movimiento del precio los obliga a cubrirse en la "
            "MISMA dirección, lo que **amplifica** la volatilidad y favorece movimientos de tendencia."
        )

    # abs(), no distancia con signo -- con signo, esto solo daba el wall
    # más cercano de verdad cuando cw1 > spot > pw1 (el layout normal). Si
    # el precio ya rompió un wall (spot > cw1, o spot < pw1 -- nada raro
    # intradía), la distancia al wall roto se vuelve negativa y "gana"
    # la comparación aunque el otro wall esté realmente mucho más cerca.
    # Un wall puede no existir (None, ver compute_call_put_walls): cuenta
    # como infinitamente lejos, y si faltan los dos no hay "más cercano".
    dist_cw1 = abs(metrics['cw1'] - spot) if metrics['cw1'] is not None else float('inf')
    dist_pw1 = abs(spot - metrics['pw1']) if metrics['pw1'] is not None else float('inf')
    if dist_cw1 == dist_pw1 == float('inf'):
        nivel_cercano = "ninguno (no hay Call/Put Wall real)"
    else:
        nivel_cercano = "Call Wall 1" if dist_cw1 <= dist_pw1 else "Put Wall 1"
    zg, cw1, cw2 = fmt_level(metrics['zero_gamma']), fmt_level(metrics['cw1']), fmt_level(metrics['cw2'])
    pw1, pw2 = fmt_level(metrics['pw1']), fmt_level(metrics['pw2'])

    return f"""**1. Estado Actual y Contexto Intradía**
Régimen de gamma: {metrics['regime_str']} ({metrics['condition_str']}). VIX en {vix_val:.2f} ({vix_status} - {vix_desc}). IV ATM {metrics['iv_str']} (percentil {metrics['iv_rank_str']}). {comportamiento}

**2. Niveles Operativos Relevantes para Scalping**
- Zero Gamma (flip): {zg} USD
- Call Wall 1 (resistencia más cercana): {cw1} USD
- Put Wall 1 (soporte más cercano): {pw1} USD
- Nivel más cercano al spot actual ({spot:.2f}): {nivel_cercano}

**3. Qué Vigilar en Order Flow**
Confirma cualquier escenario con absorción real en footprint/cumulative delta antes de entrar: una mecha de rechazo sin volumen de agresión en contra no es suficiente para operar un nivel de gamma.

**4. Escenarios Operativos (5-30 min)**
* **Rebote en Put Wall 1 → LONG**: entrada cerca de {pw1}, TP hacia {zg}, invalidación por debajo de {pw2}.
* **Rebote en Call Wall 1 → SHORT**: entrada cerca de {cw1}, TP hacia {zg}, invalidación por encima de {cw2}.
* **Ruptura y Retesteo de Zero Gamma**: si el precio sostiene por encima de {zg}, continuación LONG hacia {cw1} en el retest; si sostiene por debajo, continuación SHORT hacia {pw1} en el retest.

**5. Resumen Rápido para el Trader**

| Setup | Dirección | Entrada | TP | Invalidación | Comentario OF |
|---|---|---|---|---|---|
| Rebote PW1 | LONG | {pw1} | {zg} | {pw2} | Buscar absorción compradora en el soporte (delta grid/cumulative delta) |
| Rebote CW1 | SHORT | {cw1} | {zg} | {cw2} | Buscar absorción vendedora en la resistencia (delta grid/cumulative delta) |
| Ruptura y Retesteo ZG | Según ruptura | {zg} | {cw1} / {pw1} | Reingreso al rango | Confirmar con delta acumulado sostenido en el retest |

_Diagnóstico generado localmente (sin IA) -- conecta GROQ_API_KEY para un análisis narrativo completo._"""
