import logging

import httpx

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


async def push_live_levels(payload: dict) -> dict:
    """PUT al nodo /live_levels de Firebase Realtime Database -- mismo
    esquema y misma convención de URL (sufijo .json de la REST API de
    Firebase) que push_live_levels_to_firebase_sync en app.py, para no
    romper el indicador de Quantower ya desplegado (gamma_schwab.txt),
    que solo lee ese nodo con GET cada 10s."""
    if not settings.firebase_db_url:
        return {"ok": False, "code": None, "detail": "Falta FIREBASE_DB_URL."}

    url = f"{settings.firebase_db_url.rstrip('/')}/live_levels.json"
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.put(url, json=payload)
        if resp.status_code == 200:
            return {"ok": True, "code": resp.status_code, "detail": "OK"}
        return {"ok": False, "code": resp.status_code, "detail": resp.text[:200]}
    except Exception as e:
        # El error SÍ vuelve en el dict devuelto, pero antes nunca quedaba
        # rastro en los logs del servidor a menos que el caller lo
        # loguee explícitamente -- una caída sostenida de Firebase (el
        # indicador de Quantower deja de recibir datos) era indistinguible
        # en Render de "nadie llamó a esta función" sin este log.
        logger.exception("push_live_levels() falló.")
        return {"ok": False, "code": None, "detail": str(e)[:200]}


async def fetch_session_profile(session_key: str) -> dict | None:
    """GET de /session_profiles/{session_key}.json -- perfiles de Volume/
    Delta/TPO (Overnight 17:00-08:29 y Cash 08:30-15:00, hora Lima/UTC-5,
    ver domain/session_profile.py) que empuja el indicador de Quantower
    SessionProfilePusher.cs. None si no hay datos todavía o falla la
    lectura -- el prompt de la IA debe poder seguir armándose sin esto."""
    if not settings.firebase_db_url:
        return None

    url = f"{settings.firebase_db_url.rstrip('/')}/session_profiles/{session_key}.json"
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            return data if isinstance(data, dict) else None
    except Exception:
        # 'pass' silencioso -- una caída sostenida de Firebase acá no
        # dejaba NINGÚN rastro en los logs, indistinguible de "todavía no
        # hay perfil de sesión para esta clave" (un estado normal).
        logger.exception("fetch_session_profile(%s) falló.", session_key)
    return None
