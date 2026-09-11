import httpx

from app.config import get_settings

settings = get_settings()


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
        return {"ok": False, "code": None, "detail": str(e)[:200]}
