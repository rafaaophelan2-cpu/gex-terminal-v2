import asyncio
from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings

settings = get_settings()


@lru_cache
def get_supabase_client() -> Client | None:
    """Instancia única del cliente de Supabase para todo el proceso (mismo
    patrón que get_supabase_client en app.py, pero acá no hace falta el
    @st.cache_resource: sin reruns de Streamlit, un lru_cache normal ya
    persiste durante toda la vida del proceso)."""
    if not settings.supabase_url or not settings.supabase_key:
        return None
    return create_client(settings.supabase_url, settings.supabase_key)


async def fetch_user_by_username(username: str) -> dict | None:
    """Busca en app_users por username (case-insensitive por convención de
    login_user en app.py). supabase-py es síncrono: se corre en un thread
    aparte para no bloquear el event loop de FastAPI."""
    client = get_supabase_client()
    if client is None:
        return None

    def _query():
        res = client.table("app_users").select("*").eq("username", username).execute()
        return res.data[0] if res.data else None

    return await asyncio.to_thread(_query)


async def update_user_password_hash(username: str, new_hash: str) -> None:
    """Usado para el upgrade perezoso de SHA256 -> argon2 tras un login
    exitoso con el hash legado."""
    client = get_supabase_client()
    if client is None:
        return

    def _update():
        client.table("app_users").update({"password_hash": new_hash}).eq("username", username).execute()

    await asyncio.to_thread(_update)
