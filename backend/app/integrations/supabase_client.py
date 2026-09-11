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


async def fetch_gex_history(
    symbol: str,
    start_utc: str | None = None,
    end_utc: str | None = None,
    limit: int = 1000,
) -> list[dict]:
    """Snapshots de gex_intraday para un símbolo, ordenados cronológicamente,
    opcionalmente acotados a un rango de created_at (ISO 8601 UTC) -- usado
    para filtrar por día calendario de mercado (ver routes_rest.py). Port
    de fetch_supabase_gex_history en app.py (~línea 103)."""
    client = get_supabase_client()
    if client is None:
        return []

    def _query():
        q = client.table("gex_intraday").select("*").eq("symbol", symbol)
        if start_utc:
            q = q.gte("created_at", start_utc)
        if end_utc:
            q = q.lt("created_at", end_utc)
        res = q.order("created_at", desc=False).limit(limit).execute()
        return res.data or []

    return await asyncio.to_thread(_query)


async def fetch_available_dates(symbol: str, tz) -> list[str]:
    """Fechas calendario (YYYY-MM-DD, en la zona horaria 'tz') que tienen
    al menos un snapshot guardado para 'symbol', más recientes primero --
    usado para el selector de BACKGAMMA. Trae solo la columna created_at
    (liviano) y deriva las fechas en Python; con el volumen actual de
    datos (recién arrancado) esto alcanza sin paginar."""
    client = get_supabase_client()
    if client is None:
        return []

    def _query():
        res = (
            client.table("gex_intraday")
            .select("created_at")
            .eq("symbol", symbol)
            .order("created_at", desc=True)
            .limit(5000)
            .execute()
        )
        return res.data or []

    rows = await asyncio.to_thread(_query)

    from datetime import datetime

    dates: list[str] = []
    seen = set()
    for row in rows:
        dt = datetime.fromisoformat(row["created_at"]).astimezone(tz)
        date_str = dt.strftime("%Y-%m-%d")
        if date_str not in seen:
            seen.add(date_str)
            dates.append(date_str)
    return dates


async def insert_gex_snapshot(snapshot: dict) -> None:
    """Guarda un snapshot en gex_intraday, con el mismo dedup por
    symbol+time que push_to_supabase_bg en app.py (~línea 2598): con
    varias conexiones guardando cada ~60s de forma independiente, dos
    pueden caer casi en el mismo minuto y duplicar la fila."""
    client = get_supabase_client()
    if client is None:
        return

    def _insert():
        existing = (
            client.table("gex_intraday")
            .select("id")
            .eq("symbol", snapshot["symbol"])
            .eq("time", snapshot["time"])
            .limit(1)
            .execute()
        )
        if existing.data:
            return
        client.table("gex_intraday").insert(snapshot).execute()

    await asyncio.to_thread(_insert)
