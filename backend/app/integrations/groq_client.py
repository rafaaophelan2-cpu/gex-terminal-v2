import asyncio
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

GROQ_MODEL = "openai/gpt-oss-120b"

# Groq cuenta PROMPT + max_tokens (la reserva pedida, no lo que el
# modelo termina generando de verdad) contra el límite de Tokens Por
# Minuto de la cuenta -- confirmado en vivo en Render con un
# max_tokens FIJO (primero 4096, después 3072): el prompt de este
# sistema varía bastante de un pedido a otro (cruce con NDX con/sin
# coincidencias, calendario económico con más o menos eventos, perfiles
# de sesión presentes o no), así que un número fijo o se queda corto
# (vuelve la tabla incompleta) o se pasa del límite (413 "tokens per
# minute", CADA pedido cae al fallback local sin ni siquiera intentar
# generar nada). En vez de adivinar un número fijo, se calcula el
# presupuesto de max_tokens en base al tamaño REAL del prompt de cada
# pedido -- así nunca se pide más de lo que la cuenta permite, sin
# importar cuánto varíe el prompt.
TPM_LIMIT = 8000
# ~3.3 caracteres por token es una aproximación razonable para texto en
# español con words largas y acentos (más conservadora que la regla
# habitual de ~4 para inglés) -- sin tokenizer real disponible acá, se
# prefiere SOBREestimar tokens (subestimar el presupuesto disponible)
# antes que quedarse corto y volver a pisar el límite.
CHARS_PER_TOKEN_ESTIMATE = 3.3
# Colchón extra sobre la estimación de caracteres -- por si la
# aproximación de arriba se queda corta en un prompt particular.
SAFETY_MARGIN_TOKENS = 500
# Nunca pedir menos que esto -- confirmado en vivo que con muy poco
# margen la tabla del punto 5 sale incompleta (el problema original que
# hizo subir max_tokens la primera vez). Si el prompt es tan grande que
# ni siquiera queda este mínimo de presupuesto, mejor no intentar la
# llamada (ver _estimate_max_tokens) que gastar un pedido condenado a
# fallar por 413.
MIN_MAX_TOKENS = 1200
MAX_MAX_TOKENS = 3072


def _estimate_max_tokens(prompt_chars: int) -> int | None:
    """None si ni siquiera el mínimo entra en el presupuesto de TPM --
    el caller debe tratarlo como "no intentes la llamada, cae directo al
    fallback local" en vez de gastar un pedido que Groq va a rechazar
    igual."""
    estimated_prompt_tokens = int(prompt_chars / CHARS_PER_TOKEN_ESTIMATE)
    available = TPM_LIMIT - estimated_prompt_tokens - SAFETY_MARGIN_TOKENS
    if available < MIN_MAX_TOKENS:
        return None
    return min(available, MAX_MAX_TOKENS)


async def query_groq(system_prompt: str, user_prompt: str, history: list[dict] | None = None) -> str | None:
    """Devuelve None si no hay API key o la llamada falla -- el caller
    (routes_rest.ai-diagnosis / routes_chat.post_chat_message) debe caer
    al fallback local en ese caso, nunca dejar la pestaña DATA o el chat
    vacíos.

    'history' (opcional): turnos previos [{role, content}, ...] a incluir
    ANTES del nuevo user_prompt -- sin esto, cada llamada era una
    conversación aislada sin memoria de lo dicho antes (el chat no podía
    "relacionarse" con el usuario ni mantener contexto entre mensajes).
    Solo lo usa el chat libre; /market/ai-diagnosis no pasa history."""
    if not settings.groq_api_key:
        return None

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_prompt})

    prompt_chars = sum(len(m.get("content") or "") for m in messages)
    max_tokens = _estimate_max_tokens(prompt_chars)
    if max_tokens is None:
        # El prompt solo ya se come casi todo el presupuesto de TPM de la
        # cuenta -- ni vale la pena intentar la llamada (Groq la va a
        # rechazar con 413 igual), cae directo al fallback local sin
        # gastar la ventana de rate limit de este minuto en un pedido
        # condenado a fallar.
        logger.warning(
            "query_groq(): prompt de ~%d caracteres deja muy poco presupuesto de TPM -- se omite el llamado a Groq esta vez.",
            prompt_chars,
        )
        return None

    def _call() -> str:
        from groq import Groq

        client = Groq(api_key=settings.groq_api_key)
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=max_tokens,
        )
        return completion.choices[0].message.content

    try:
        return await asyncio.to_thread(_call)
    except Exception:
        # Antes se tragaba en silencio -- confirmado en vivo que eso hacía
        # IMPOSIBLE diagnosticar por qué el diagnóstico caía al fallback
        # local (ni siquiera se sabía si la excepción era por key inválida,
        # modelo deprecado, rate limit de Groq, o timeout de red) -- mismo
        # motivo que ya se corrigió antes en marketdata_client.py y
        # forexfactory_client.py: sin loggear ACÁ, un fallo sostenido de
        # Groq es indistinguible de "no hay API key configurada".
        logger.exception("query_groq() falló -- cae al diagnóstico local por plantilla.")
        return None
