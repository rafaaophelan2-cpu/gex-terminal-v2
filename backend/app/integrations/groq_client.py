import asyncio
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

GROQ_MODEL = "openai/gpt-oss-120b"


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

    def _call() -> str:
        from groq import Groq

        client = Groq(api_key=settings.groq_api_key)
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_prompt})

        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.3,
            # 3072 (antes 4096, y antes de eso sin setear) -- confirmado en
            # vivo en Render el motivo real de cada valor:
            # - sin setear: la tabla del punto 5 salía incompleta (1 de 3
            #   filas, celdas vacías), cortada por el máximo default.
            # - 4096: el prompt de este sistema (framework completo +
            #   calendario económico de la semana, ver ai_prompt.py) creció
            #   a lo largo de la sesión hasta ~4300 tokens -- Groq cuenta
            #   prompt + max_tokens (NO tokens realmente generados) contra
            #   el límite de Tokens Por Minuto de la cuenta (8000 TPM en
            #   este tier), así que 4300 + 4096 = 8396 superaba el límite
            #   en CADA pedido (error 413 "tokens per minute", nunca
            #   llegaba a generar nada -- confirmado con logger.exception
            #   de acá abajo). 3072 deja margen real (~4300 + 3072 = 7372)
            #   incluso en una semana con calendario económico cargado, sin
            #   volver a la tabla incompleta del primer problema.
            max_tokens=3072,
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
