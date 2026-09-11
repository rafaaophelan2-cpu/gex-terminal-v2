import asyncio
from datetime import datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from supabase import Client, create_client

from app.config import get_settings

settings = get_settings()

# El dedup de insert_gex_snapshot compara por symbol+time ("HH:MM", sin
# fecha) -- necesita acotarse al día de mercado en curso para no confundir
# el "09:30" de hoy con el "09:30" ya guardado ayer. Mismo criterio de
# zona horaria que STORAGE_TZ en snapshot_writer.py.
_NY_TZ = ZoneInfo("America/New_York")


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
    al menos un snapshot DENTRO del horario de mercado (09:30-16:00 NY)
    para 'symbol', más recientes primero -- usado tanto por el selector
    de BACKGAMMA como por LIVE GAMMA para resolver "la última sesión"
    (dates[0] en el frontend). Trae created_at + time (liviano) y filtra
    en Python; con el volumen actual de datos esto alcanza sin paginar.

    El filtro de horario importa incluso con snapshot_writer ya
    gateado a horas de mercado (ver snapshot_writer.py): filas viejas de
    ANTES de ese fix, o cualquier fila fuera de horario insertada por
    otra vía, no deben hacer que este símbolo apunte a un día sin
    ninguna fila útil para el heatmap/drift -- eso dejaba LIVE GAMMA en
    blanco hasta que abriera el mercado real."""
    client = get_supabase_client()
    if client is None:
        return []

    def _query():
        res = (
            client.table("gex_intraday")
            .select("created_at, time")
            .eq("symbol", symbol)
            .order("created_at", desc=True)
            .limit(5000)
            .execute()
        )
        return res.data or []

    rows = await asyncio.to_thread(_query)

    from datetime import datetime

    from app.domain.drift import DEFAULT_SESSION_END, DEFAULT_SESSION_START

    dates: list[str] = []
    seen = set()
    for row in rows:
        time_str = row.get("time", "")
        if not (DEFAULT_SESSION_START <= time_str <= DEFAULT_SESSION_END):
            continue
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
    pueden caer casi en el mismo minuto y duplicar la fila.

    'time' es solo "HH:MM" (sin fecha) -- comparado a secas, el "09:30"
    de hoy calza con el "09:30" ya guardado cualquier día anterior y el
    insert se descarta como si fuera un duplicado real, dejando el
    símbolo sin ningún snapshot nuevo apenas se repite el horario de
    mercado (bug encontrado en vivo: LIVE GAMMA quedaba vacío el mismo
    día que se agotaban los "HH:MM" ya vistos en días previos). El dedup
    se acota al día de mercado en curso (NY) para que solo bloquee
    duplicados reales dentro del mismo día."""
    client = get_supabase_client()
    if client is None:
        return

    day_start = datetime.now(_NY_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    def _insert():
        existing = (
            client.table("gex_intraday")
            .select("id")
            .eq("symbol", snapshot["symbol"])
            .eq("time", snapshot["time"])
            .gte("created_at", day_start.isoformat())
            .lt("created_at", day_end.isoformat())
            .limit(1)
            .execute()
        )
        if existing.data:
            return
        client.table("gex_intraday").insert(snapshot).execute()

    await asyncio.to_thread(_insert)
