import asyncio

from app.config import get_settings

settings = get_settings()

GROQ_MODEL = "openai/gpt-oss-120b"


async def query_groq(system_prompt: str, user_prompt: str) -> str | None:
    """Devuelve None si no hay API key o la llamada falla -- el caller
    (routes_rest.ai-diagnosis) debe caer al fallback local en ese caso,
    nunca dejar la pestaña DATA vacía."""
    if not settings.groq_api_key:
        return None

    def _call() -> str:
        from groq import Groq

        client = Groq(api_key=settings.groq_api_key)
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )
        return completion.choices[0].message.content

    try:
        return await asyncio.to_thread(_call)
    except Exception:
        return None
