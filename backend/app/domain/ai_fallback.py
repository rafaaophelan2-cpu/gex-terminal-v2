from app.domain.ai_prompt import classify_vix


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

    dist_cw1 = metrics['cw1'] - spot
    dist_pw1 = spot - metrics['pw1']
    nivel_cercano = "Call Wall 1" if dist_cw1 <= dist_pw1 else "Put Wall 1"

    return f"""**1. Estado Actual y Contexto Intradía**
Régimen de gamma: {metrics['regime_str']} ({metrics['condition_str']}). VIX en {vix_val:.2f} ({vix_status} - {vix_desc}). IV ATM {metrics['iv_str']} (percentil {metrics['iv_rank_str']}). {comportamiento}

**2. Niveles Operativos Relevantes para Scalping**
- Zero Gamma (flip): {metrics['zero_gamma']:.2f} USD
- Call Wall 1 (resistencia más cercana): {metrics['cw1']:.2f} USD
- Put Wall 1 (soporte más cercano): {metrics['pw1']:.2f} USD
- Nivel más cercano al spot actual ({spot:.2f}): {nivel_cercano}

**3. Qué Vigilar en Order Flow**
Confirma cualquier escenario con absorción real en footprint/cumulative delta antes de entrar: una mecha de rechazo sin volumen de agresión en contra no es suficiente para operar un nivel de gamma.

**4. Escenarios Operativos (5-30 min)**
* **Rebote en Put Wall 1 → LONG**: entrada cerca de {metrics['pw1']:.2f}, TP hacia {metrics['zero_gamma']:.2f}, invalidación por debajo de {metrics['pw2']:.2f}.
* **Rebote en Call Wall 1 → SHORT**: entrada cerca de {metrics['cw1']:.2f}, TP hacia {metrics['zero_gamma']:.2f}, invalidación por encima de {metrics['cw2']:.2f}.
* **Ruptura y Retesteo de Zero Gamma**: si el precio sostiene por encima de {metrics['zero_gamma']:.2f}, continuación LONG hacia {metrics['cw1']:.2f} en el retest; si sostiene por debajo, continuación SHORT hacia {metrics['pw1']:.2f} en el retest.

**5. Resumen Rápido para el Trader**

| Setup | Dirección | Entrada | TP | Invalidación | Comentario OF |
|---|---|---|---|---|---|
| Rebote PW1 | LONG | {metrics['pw1']:.2f} | {metrics['zero_gamma']:.2f} | {metrics['pw2']:.2f} | Buscar absorción compradora en el soporte (delta grid/cumulative delta) |
| Rebote CW1 | SHORT | {metrics['cw1']:.2f} | {metrics['zero_gamma']:.2f} | {metrics['cw2']:.2f} | Buscar absorción vendedora en la resistencia (delta grid/cumulative delta) |
| Ruptura y Retesteo ZG | Según ruptura | {metrics['zero_gamma']:.2f} | {metrics['cw1']:.2f} / {metrics['pw1']:.2f} | Reingreso al rango | Confirmar con delta acumulado sostenido en el retest |

_Diagnóstico generado localmente (sin IA) -- conecta GROQ_API_KEY para un análisis narrativo completo._"""
